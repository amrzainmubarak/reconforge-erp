from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from reconforge.benchmark.postgres_durable_job_backpressure import (
    POSTGRES_BACKPRESSURE_PROFILE_ID,
    PostgresDurableJobBackpressureProfile,
    default_profile,
)


def test_postgres_backpressure_profile_is_bounded_and_lane_fair() -> None:
    profile = default_profile()

    assert profile.profile_id == POSTGRES_BACKPRESSURE_PROFILE_ID
    assert profile.jobs == 64
    assert profile.declared_partition_effects == 256
    assert profile.workers // profile.tenants == 2
    assert profile.max_queued_jobs == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"workers": 0},
        {"workers": 3},
        {"tenants": 0},
        {"max_queued_jobs": 0},
        {"max_queued_jobs": 17},
    ],
)
def test_postgres_backpressure_profile_rejects_invalid_shape(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        PostgresDurableJobBackpressureProfile(**changes)


def test_postgres_backpressure_profile_is_packaged_documented_and_selected_in_ci() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/postgres_durable_job_backpressure.py" in manifest
    assert "include tests/test_postgres_durable_job_backpressure.py" in manifest
    assert "include docs/execution/benchmarks/postgres-durable-job-backpressure-tier-v1.md" in manifest
    assert "include docs/execution/benchmarks/postgres-durable-job-backpressure-tier-v1.json" in manifest
    assert "include docs/adr/0340-postgres-durable-job-backpressure-runtime-gate.md" in manifest
    artifact = json.loads(
        (root / "docs/execution/benchmarks/postgres-durable-job-backpressure-tier-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["profile_id"] == POSTGRES_BACKPRESSURE_PROFILE_ID
    assert artifact["submitted_jobs"] == artifact["completed_jobs"] == 64
    assert artifact["committed_partition_effects"] == 256
    assert artifact["observed_max_queue_depth"] == artifact["max_queued_jobs"] == 4
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    runs = [step.get("run", "") for step in workflow["jobs"]["server-boundaries"]["steps"]]
    assert any("test_live_postgres_durable_job_backpressure_profile" in run for run in runs)


def test_current_postgres_backpressure_report_is_digest_bound() -> None:
    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "docs/execution/benchmarks/postgres-durable-job-backpressure-current-2026-08-06.json").read_text(
            encoding="utf-8"
        )
    )
    supplied = str(report.pop("report_digest"))
    canonical = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert report["invariants"]["completed_jobs"] == report["invariants"]["submitted_jobs"] == 64
    assert report["invariants"]["observed_max_queue_depth"] == report["invariants"]["max_queued_jobs"] == 4
