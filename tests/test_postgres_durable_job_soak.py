from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reconforge.benchmark.postgres_durable_job_scale import PostgresDurableJobScaleProfile
from reconforge.benchmark.postgres_durable_job_soak import (
    DEFAULT_POSTGRES_SOAK_ITERATIONS,
    DEFAULT_POSTGRES_SOAK_PROFILE_ID,
    LIMITATIONS,
    POSTGRES_SOAK_SCHEMA_VERSION,
    PostgresDurableJobSoakProfile,
    run_postgres_durable_job_soak_profile,
    verify_postgres_durable_job_soak_result,
)


def _small() -> PostgresDurableJobSoakProfile:
    return PostgresDurableJobSoakProfile(
        profile_id="postgres-durable-job-soak/test-tier-v1",
        iterations=2,
        scale_profile=PostgresDurableJobScaleProfile(
            profile_id="postgres-durable-job-soak/load-tier-v1",
            workers=4,
            jobs_per_tenant=2,
            partitions_per_job=2,
            tenants=2,
        ),
    )


def test_default_postgres_soak_profile_shape() -> None:
    profile = PostgresDurableJobSoakProfile()
    assert profile.profile_id == DEFAULT_POSTGRES_SOAK_PROFILE_ID
    assert profile.iterations == DEFAULT_POSTGRES_SOAK_ITERATIONS
    assert profile.declared_scale_profile.jobs == 64
    assert profile.declared_scale_profile.declared_partition_effects == 256


def test_postgres_soak_profile_rejects_invalid_iteration_bounds() -> None:
    with pytest.raises(ValueError, match="between 2 and 16"):
        PostgresDurableJobSoakProfile(iterations=1)
    with pytest.raises(ValueError, match="between 2 and 16"):
        PostgresDurableJobSoakProfile(iterations=17)


def test_postgres_soak_profile_requires_unique_lanes_and_stable_prefix() -> None:
    profile = _small()
    with pytest.raises(ValueError, match="one lane set"):
        run_postgres_durable_job_soak_profile(object(), object(), (("a", "b"),), profile=profile)
    with pytest.raises(ValueError, match="unique declared tenant"):
        run_postgres_durable_job_soak_profile(
            object(), object(), (("a", "a"), ("c", "d")), profile=profile
        )
    with pytest.raises(ValueError, match="unique across iterations"):
        run_postgres_durable_job_soak_profile(
            object(), object(), (("a", "b"), ("b", "c")), profile=profile
        )
    with pytest.raises(ValueError, match="bounded non-empty"):
        run_postgres_durable_job_soak_profile(
            object(), object(), (("a", "b"), ("c", "d")), profile=profile, id_prefix=""
        )


def test_postgres_soak_verifier_fails_closed_on_digest_drift() -> None:
    profile = _small()
    from reconforge.benchmark.postgres_durable_job_soak import PostgresDurableJobSoakResult

    result = PostgresDurableJobSoakResult(
        schema_version=POSTGRES_SOAK_SCHEMA_VERSION,
        profile_id=profile.profile_id,
        iterations=2,
        jobs_per_iteration=4,
        partitions_per_job=2,
        total_jobs=8,
        total_partition_effects=16,
        duplicate_partition_effects=0,
        nonzero_queue_or_running_runs=0,
        effect_digests=("a" * 64, "b" * 64),
        aggregate_effect_digest="c" * 64,
        observed_runtime_seconds=0.1,
        environment={"database": "PostgreSQL"},
        limitations=LIMITATIONS,
    )
    with pytest.raises(AssertionError, match="digest changed"):
        verify_postgres_durable_job_soak_result(result, profile=profile)


def test_postgres_soak_profile_is_packaged_and_selected_in_ci() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/postgres_durable_job_soak.py" in manifest
    assert "include tests/test_postgres_durable_job_soak.py" in manifest
    assert "include docs/adr/0510-postgres-durable-job-repeated-soak.md" in manifest
    assert "include docs/execution/benchmarks/postgres-durable-job-soak-current-2026-08-10.json" in manifest
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "test_live_postgres_durable_job_soak_profile" in workflow


def test_current_postgres_soak_report_is_digest_bound() -> None:
    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "docs/execution/benchmarks/postgres-durable-job-soak-current-2026-08-10.json").read_text(
            encoding="utf-8"
        )
    )
    supplied = str(report.pop("report_digest"))
    canonical = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert report["invariants"]["total_jobs"] == 192
    assert report["invariants"]["total_partition_effects"] == 768
    assert len(set(report["effect_digests"])) == 1
