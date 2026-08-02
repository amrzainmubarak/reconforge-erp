from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.benchmark.durable_job_retry import (
    DurableJobRetryProfile,
    default_retry_profile,
    run_durable_job_retry_profile,
    verify_retry_manifest,
)


def test_retry_profile_proves_checkpoint_resume_without_duplicate_effects(tmp_path: Path) -> None:
    profile = default_retry_profile(workers=2, jobs=4, partitions_per_job=3, tenants=2)
    result = run_durable_job_retry_profile(tmp_path / "retry.db", profile=profile)

    verify_retry_manifest(result, profile=profile)
    assert result.scheduled_retries == 4
    assert result.committed_partition_effects == 12
    assert result.duplicate_partition_effects == 0
    assert result.max_retry_count == 1


def test_retry_manifest_digest_is_reproducible_for_same_shape(tmp_path: Path) -> None:
    profile = default_retry_profile(workers=2, jobs=4, partitions_per_job=2, tenants=2)
    first = run_durable_job_retry_profile(tmp_path / "first.db", profile=profile)
    second = run_durable_job_retry_profile(tmp_path / "second.db", profile=profile)

    assert first.effect_set_digest == second.effect_set_digest
    assert first.manifest_digest == second.manifest_digest


def test_retry_profile_rejects_faults_above_ceiling() -> None:
    with pytest.raises(ValueError, match="retry_ceiling"):
        DurableJobRetryProfile(
            profile_id="retry",
            workers=2,
            jobs=2,
            partitions_per_job=2,
            tenants=2,
            transient_failures_per_job=2,
            retry_ceiling=1,
            lease_seconds=10,
        )


def test_retry_profile_requires_fair_worker_distribution() -> None:
    with pytest.raises(ValueError, match="exact multiple"):
        default_retry_profile(workers=3, jobs=4, partitions_per_job=2, tenants=2)


def test_retry_profile_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/durable_job_retry.py" in manifest
    assert "include tests/test_durable_job_retry_profile.py" in manifest
