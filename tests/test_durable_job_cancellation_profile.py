from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.benchmark.durable_job_cancellation import (
    DEFAULT_CANCEL_JOBS,
    DEFAULT_CANCEL_JOBS_TO_CANCEL,
    DEFAULT_CANCEL_PARTITIONS_PER_JOB,
    DEFAULT_CANCEL_PROFILE_ID,
    DEFAULT_CANCEL_TENANTS,
    DEFAULT_CANCEL_WORKERS,
    LIMITATIONS,
    LOAD_CANCEL_SCHEMA_VERSION,
    DurableJobCancelProfile,
    default_cancel_profile,
    run_durable_job_cancellation_profile,
    run_durable_job_running_cancel_profile,
    verify_cancel_manifest,
    verify_running_cancel_manifest,
)


def _small() -> DurableJobCancelProfile:
    return DurableJobCancelProfile(
        profile_id="durable-job-cancel/test-tier-v1",
        workers=4,
        jobs=8,
        partitions_per_job=2,
        tenants=2,
        jobs_to_cancel=2,
        lease_seconds=30,
    )


def test_profile_validation_rejects_invalid_shapes() -> None:
    with pytest.raises(ValueError, match="exact multiple of tenants"):
        DurableJobCancelProfile("bad", 3, 4, 1, 2, 1, 1)
    with pytest.raises(ValueError, match="jobs_to_cancel"):
        DurableJobCancelProfile("bad", 1, 1, 1, 1, 2, 1)
    with pytest.raises(ValueError, match="workers must be at least"):
        DurableJobCancelProfile("bad", 0, 1, 1, 1, 0, 1)


def test_default_profile_matches_declared_small_tier() -> None:
    profile = default_cancel_profile()
    assert profile.profile_id == DEFAULT_CANCEL_PROFILE_ID
    assert profile.workers == DEFAULT_CANCEL_WORKERS
    assert profile.jobs == DEFAULT_CANCEL_JOBS
    assert profile.partitions_per_job == DEFAULT_CANCEL_PARTITIONS_PER_JOB
    assert profile.tenants == DEFAULT_CANCEL_TENANTS
    assert profile.jobs_to_cancel == DEFAULT_CANCEL_JOBS_TO_CANCEL
    assert profile.declared_partition_effects == (64 - 16) * 4 == 192


def test_queued_cancellation_drains_without_duplicate_effects(tmp_path: Path) -> None:
    profile = _small()
    result = run_durable_job_cancellation_profile(tmp_path / "cancel.db", profile=profile)
    verify_cancel_manifest(result, profile=profile)
    assert result.completed_jobs == 6
    assert result.cancelled_jobs == 2
    assert result.committed_partition_effects == 12
    assert result.duplicate_partition_effects == 0
    assert result.final_queue_depth == result.final_running_depth == result.orphaned_leases == 0
    # Runtime is an observation rounded to four decimals; a fast running path
    # may legitimately round to zero and is excluded from structural evidence.
    assert result.observed_runtime_seconds >= 0
    assert result.observed_peak_memory_mb > 0


def test_queued_cancellation_structural_digest_is_reproducible(tmp_path: Path) -> None:
    profile = _small()
    first = run_durable_job_cancellation_profile(tmp_path / "first.db", profile=profile)
    second = run_durable_job_cancellation_profile(tmp_path / "second.db", profile=profile)
    verify_cancel_manifest(first, profile=profile)
    verify_cancel_manifest(second, profile=profile)
    assert first.effect_set_digest == second.effect_set_digest
    assert first.manifest_digest == second.manifest_digest
    assert first.to_dict()["limitations"] == list(LIMITATIONS)


def test_running_cancellation_releases_lease_without_duplicate_effects(tmp_path: Path) -> None:
    result = run_durable_job_running_cancel_profile(tmp_path / "running.db", partitions_before_cancel=1, total_partitions=3)
    verify_running_cancel_manifest(result)
    assert result.final_job_status == "cancelled"
    assert result.committed_partition_effects == 1
    assert result.lease_released is True
    assert result.duplicate_partition_effects == result.orphaned_leases == 0
    # Runtime is an observation rounded to four decimals; this deliberately
    # tiny path may legitimately round to zero.
    assert result.observed_runtime_seconds >= 0


def test_manifest_text_is_closed_schema_and_retains_limitations(tmp_path: Path) -> None:
    profile = _small()
    result = run_durable_job_cancellation_profile(tmp_path / "manifest.db", profile=profile)
    document = json.loads(result.to_manifest_text())
    assert document["schema_version"] == LOAD_CANCEL_SCHEMA_VERSION
    assert document["profile_id"] == profile.profile_id
    assert document["declared_partition_effects"] == 12
    assert document["completed_jobs"] + document["cancelled_jobs"] == profile.jobs
    assert document["manifest_digest"] == result.manifest_digest
    assert len(document["limitations"]) == len(LIMITATIONS)
    assert "not a scale" in " ".join(document["limitations"])


def test_schema_runtime_docs_and_tests_are_in_distribution_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    expected = {
        "include reconforge/benchmark/durable_job_cancellation.py",
        "include tests/test_durable_job_cancellation_profile.py",
        "include docs/adr/0214-durable-job-cancellation-profile-is-structural-and-non-claim.md",
    }
    assert expected <= set(manifest.splitlines())
