from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from reconforge.benchmark.postgres_durable_job_scale import (
    PostgresDurableJobScaleProfile,
    default_profile,
    ten_k_profile,
)


def test_postgres_scale_profile_declares_partitioned_multi_tenant_shape() -> None:
    profile = default_profile()
    assert profile.profile_id == "postgres-durable-job-load/256-effects-v1"
    assert profile.workers == 8
    assert profile.jobs == 64
    assert profile.jobs_per_tenant == 16
    assert profile.partitions_per_job == 4
    assert profile.tenants == 4
    assert profile.declared_partition_effects == 256
    assert profile.workers % profile.tenants == 0


def test_postgres_scale_profile_declares_10k_effect_tier() -> None:
    profile = ten_k_profile()
    assert profile.profile_id == "postgres-durable-job-load/10k-effects-v1"
    assert profile.workers == 16
    assert profile.jobs == 2_500
    assert profile.jobs_per_tenant == 625
    assert profile.partitions_per_job == 4
    assert profile.tenants == 4
    assert profile.declared_partition_effects == 10_000
    assert profile.workers % profile.tenants == 0


def test_postgres_scale_profile_is_packaged_and_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/postgres_durable_job_scale.py" in manifest
    assert "include tests/test_postgres_durable_job_scale.py" in manifest
    assert (root / "docs/adr/0297-postgres-durable-job-bounded-scale-profile.md").is_file()
    assert (root / "docs/execution/benchmarks/postgres-durable-job-256-effects-v1.md").is_file()
    assert "include docs/execution/benchmarks/postgres-durable-job-10k-effects-v1.md" in manifest
    assert "include docs/execution/benchmarks/postgres-durable-job-10k-effects-v1.json" in manifest
    assert "include docs/schemas/postgres_durable_job_scale.schema.json" in manifest
    assert "include docs/adr/0306-postgres-durable-job-10k-scale.md" in manifest
    assert (root / "docs/adr/0306-postgres-durable-job-10k-scale.md").is_file()
    assert (root / "docs/execution/benchmarks/postgres-durable-job-10k-effects-v1.json").is_file()


def test_published_10k_artifact_is_schema_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs/schemas/postgres_durable_job_scale.schema.json").read_text(encoding="utf-8"))
    artifact = json.loads(
        (root / "docs/execution/benchmarks/postgres-durable-job-10k-effects-v1.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(artifact)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"workers": 0},
        {"jobs_per_tenant": 0},
        {"partitions_per_job": 0},
        {"tenants": 0},
        {"workers": 3, "tenants": 2},
        {"lease_seconds": 0},
    ],
)
def test_postgres_scale_profile_rejects_invalid_shape(kwargs: dict[str, int]) -> None:
    values = {
        "profile_id": "invalid",
        "workers": 8,
        "jobs_per_tenant": 2,
        "partitions_per_job": 2,
        "tenants": 2,
        "lease_seconds": 60,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        PostgresDurableJobScaleProfile(**values)
