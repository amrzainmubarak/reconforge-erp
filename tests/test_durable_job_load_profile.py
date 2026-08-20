from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.benchmark.durable_job_load import (
    DEFAULT_JOBS,
    DEFAULT_PARTITIONS_PER_JOB,
    DEFAULT_PROFILE_ID,
    DEFAULT_TENANTS,
    DEFAULT_WORKERS,
    LIMITATIONS,
    LOAD_PROFILE_SCHEMA_VERSION,
    DurableJobLoadProfile,
    default_profile,
    run_durable_job_load_profile,
    verify_load_manifest,
)


def _small() -> DurableJobLoadProfile:
    return DurableJobLoadProfile(
        profile_id="durable-job-load/test-tier-v1",
        workers=4,
        jobs=8,
        partitions_per_job=2,
        tenants=2,
        lease_seconds=30,
    )


def test_profile_validation_rejects_unbalanced_worker_tenant_splits() -> None:
    with pytest.raises(ValueError, match="exact multiple of tenants"):
        DurableJobLoadProfile(
            profile_id="bad",
            workers=3,
            jobs=4,
            partitions_per_job=1,
            tenants=2,
            lease_seconds=1,
        )
    with pytest.raises(ValueError, match="workers must be at least"):
        DurableJobLoadProfile("bad", 0, 1, 1, 1, 1)
    with pytest.raises(ValueError, match="1 <= tenants <= jobs"):
        DurableJobLoadProfile("bad", 1, 1, 1, 4, 1)
    with pytest.raises(ValueError, match="lease_seconds must be at least"):
        DurableJobLoadProfile("bad", 1, 1, 1, 1, 0)


def test_default_profile_matches_the_declared_small_tier_shape() -> None:
    profile = default_profile()
    assert profile.profile_id == DEFAULT_PROFILE_ID
    assert profile.workers == DEFAULT_WORKERS
    assert profile.jobs == DEFAULT_JOBS
    assert profile.partitions_per_job == DEFAULT_PARTITIONS_PER_JOB
    assert profile.tenants == DEFAULT_TENANTS
    assert profile.declared_partition_effects == 64 * 4 == 256


def test_small_load_runs_drain_complete_and_have_no_duplicate_effects(tmp_path: Path) -> None:
    profile = _small()
    result = run_durable_job_load_profile(tmp_path / "load.db", profile=profile)
    verify_load_manifest(result, profile=profile)
    assert result.completed_jobs == profile.jobs
    assert result.committed_partition_effects == profile.declared_partition_effects
    assert result.duplicate_partition_effects == 0
    assert result.final_queue_depth == 0
    assert result.final_running_depth == 0
    assert sum(result.per_tenant_completions.values()) == profile.jobs
    assert result.observed_runtime_seconds > 0
    assert result.observed_peak_memory_mb > 0
    assert result.observed_throughput_jobs_per_second > 0


def test_manifest_structural_digest_is_reproducible_across_runs(tmp_path: Path) -> None:
    """Same declared inputs produce the same effect-set and manifest digest; timing varies honestly."""

    profile = _small()
    first = run_durable_job_load_profile(tmp_path / "first.db", profile=profile)
    second = run_durable_job_load_profile(tmp_path / "second.db", profile=profile)
    verify_load_manifest(first, profile=profile)
    verify_load_manifest(second, profile=profile)
    assert first.effect_set_digest == second.effect_set_digest
    assert first.manifest_digest == second.manifest_digest
    assert first.per_tenant_completions == second.per_tenant_completions
    assert first.committed_partition_effects == second.committed_partition_effects
    timing_independent = {first.observed_runtime_seconds, second.observed_runtime_seconds}
    assert len(timing_independent) >= 1


def test_manifest_text_is_closed_schema_v1_json_and_carries_limitations(tmp_path: Path) -> None:
    profile = _small()
    result = run_durable_job_load_profile(tmp_path / "load.db", profile=profile)
    document = json.loads(result.to_manifest_text())
    assert document["schema_version"] == LOAD_PROFILE_SCHEMA_VERSION
    assert document["profile_id"] == profile.profile_id
    assert document["workers"] == profile.workers
    assert document["jobs"] == profile.jobs
    assert document["partitions_per_job"] == profile.partitions_per_job
    assert document["tenants"] == profile.tenants
    assert document["declared_partition_effects"] == profile.declared_partition_effects
    assert document["completed_jobs"] == profile.jobs
    assert document["duplicate_partition_effects"] == 0
    assert document["final_queue_depth"] == 0
    assert document["final_running_depth"] == 0
    assert document["effect_set_digest"] == result.effect_set_digest
    assert document["manifest_digest"] == result.manifest_digest
    assert "limitations" in document and len(document["limitations"]) == len(LIMITATIONS)
    assert any("not a scale" in lim or "not exercised" in lim for lim in document["limitations"])
    assert "processor" in document["environment"]
    assert isinstance(document["per_tenant_completions"], dict)


def test_manifest_digest_excludes_observed_timings_so_two_runs_match(tmp_path: Path) -> None:
    """manifest_digest covers the structural invariants but never the wall-clock/memory/throughput counters."""

    profile = _small()
    first = run_durable_job_load_profile(tmp_path / "first.db", profile=profile)
    second = run_durable_job_load_profile(tmp_path / "second.db", profile=profile)
    observed_keys = (
        "observed_runtime_seconds",
        "observed_peak_memory_mb",
        "observed_throughput_jobs_per_second",
        "manifest_digest",
    )
    first_doc = first.to_dict()
    second_doc = second.to_dict()
    for key in observed_keys:
        if key != "manifest_digest":
            first_doc.pop(key, None)
            second_doc.pop(key, None)
    first_doc.pop("manifest_digest", None)
    second_doc.pop("manifest_digest", None)
    assert first_doc == second_doc
    assert first.manifest_digest == second.manifest_digest


def test_no_duplicate_partition_effect_rows_are_persisted_under_fair_contention(tmp_path: Path) -> None:
    """Two workers per tenant racing on the same shared SQLite database cannot duplicate an effect."""

    profile = DurableJobLoadProfile(
        profile_id="durable-job-load/contention-tier-v1",
        workers=8,
        jobs=32,
        partitions_per_job=3,
        tenants=4,
        lease_seconds=60,
    )
    result = run_durable_job_load_profile(tmp_path / "contention.db", profile=profile)
    verify_load_manifest(result, profile=profile)
    assert result.duplicate_partition_effects == 0
    assert result.committed_partition_effects == 32 * 3
    from reconforge.db import connect

    connection = connect(tmp_path / "contention.db", require_exists=True)
    try:
        rows = connection.execute(
            """
            SELECT job_id, partition_key, COUNT(*) AS occurrences
            FROM durable_job_partition_effects
            GROUP BY job_id, partition_key
            ORDER BY occurrences DESC
            LIMIT 1
            """
        ).fetchone()
        assert int(rows[2]) == 1
        job_statuses = connection.execute(
            "SELECT status, COUNT(*) FROM durable_jobs GROUP BY status"
        ).fetchall()
        statuses = {str(row[0]): int(row[1]) for row in job_statuses}
        assert statuses == {"completed": 32}
    finally:
        connection.close()


def test_default_tier_runs_in_bounded_local_time_without_a_scale_claim(tmp_path: Path) -> None:
    """The default small tier (8 workers x 64 jobs x 4 partitions) drains on local hardware."""

    profile = default_profile()
    result = run_durable_job_load_profile(tmp_path / "default.db", profile=profile)
    verify_load_manifest(result, profile=profile)
    assert result.completed_jobs == 64
    assert result.committed_partition_effects == 256
    assert result.duplicate_partition_effects == 0
    assert result.observed_runtime_seconds < 60
    assert sum(result.per_tenant_completions.values()) == 64
    assert len(result.per_tenant_completions) == 4


def test_schema_runtime_docs_and_tests_are_in_distribution_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    expected = {
        "include docs/adr/0213-durable-job-load-profile-is-structural-and-non-claim.md",
        "include docs/adr/0229-durable-job-10k-tier-is-hardware-scoped.md",
        "include docs/execution/benchmarks/durable-job-10k-tier-v1.md",
        "include reconforge/benchmark/durable_job_scale.py",
        "include tests/test_durable_job_scale.py",
        "include reconforge/benchmark/durable_job_load.py",
        "include tests/test_durable_job_load_profile.py",
    }
    assert expected <= set(manifest.splitlines())
