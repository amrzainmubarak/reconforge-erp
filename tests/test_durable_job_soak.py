from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.benchmark.durable_job_load import DurableJobLoadProfile
from reconforge.benchmark.durable_job_soak import (
    DEFAULT_ITERATIONS,
    DEFAULT_SOAK_PROFILE_ID,
    LIMITATIONS,
    SOAK_SCHEMA_VERSION,
    DurableJobSoakProfile,
    run_durable_job_soak_profile,
    verify_soak_manifest,
)


def _small() -> DurableJobSoakProfile:
    return DurableJobSoakProfile(
        profile_id="durable-job-soak/test-tier-v1",
        iterations=2,
        load_profile=DurableJobLoadProfile(
            profile_id="durable-job-soak/load-tier-v1",
            workers=4,
            jobs=8,
            partitions_per_job=2,
            tenants=2,
            lease_seconds=30,
        ),
    )


def test_default_soak_profile_shape() -> None:
    profile = DurableJobSoakProfile()
    assert profile.profile_id == DEFAULT_SOAK_PROFILE_ID
    assert profile.iterations == DEFAULT_ITERATIONS
    assert profile.declared_load_profile.jobs == 64


def test_soak_profile_rejects_invalid_iteration_bounds() -> None:
    with pytest.raises(ValueError, match="between 2 and 32"):
        DurableJobSoakProfile(iterations=1)
    with pytest.raises(ValueError, match="between 2 and 32"):
        DurableJobSoakProfile(iterations=33)


def test_repeated_load_preserves_digest_and_drains_every_iteration(tmp_path: Path) -> None:
    profile = _small()
    result = run_durable_job_soak_profile(tmp_path / "soak.db", profile=profile)

    verify_soak_manifest(result, profile=profile)
    assert result.total_jobs == 16
    assert result.total_partition_effects == 32
    assert result.duplicate_partition_effects == 0
    assert result.nonzero_queue_or_running_runs == 0
    assert len(result.effect_digests) == 2
    assert len(set(result.effect_digests)) == 1
    assert result.observed_runtime_seconds > 0
    assert result.observed_peak_memory_mb > 0


def test_soak_manifest_is_closed_and_replayable(tmp_path: Path) -> None:
    profile = _small()
    first = run_durable_job_soak_profile(tmp_path / "first.db", profile=profile)
    second = run_durable_job_soak_profile(tmp_path / "second.db", profile=profile)
    verify_soak_manifest(first, profile=profile)
    verify_soak_manifest(second, profile=profile)
    assert first.effect_digests == second.effect_digests
    assert first.aggregate_effect_digest == second.aggregate_effect_digest
    document = json.loads(first.to_manifest_text())
    assert document["schema_version"] == SOAK_SCHEMA_VERSION
    assert document["limitations"] == list(LIMITATIONS)
    assert document["aggregate_effect_digest"] == first.aggregate_effect_digest


def test_soak_profile_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/durable_job_soak.py" in manifest
    assert "include tests/test_durable_job_soak.py" in manifest
    assert "include docs/adr/0384-durable-job-repeated-soak-profile.md" in manifest
