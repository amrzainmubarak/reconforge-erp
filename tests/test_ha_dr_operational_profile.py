from __future__ import annotations

import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def test_ha_dr_operational_profile_is_closed_and_consistent_with_repeated_report() -> None:
    profile = json.loads(
        (ROOT / "docs/operations/HA_DR_OPERATIONAL_PROFILE_2026-07-30.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/ha_dr_operational_profile.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(profile)
    report = json.loads((ROOT / profile["source_report"]).read_text(encoding="utf-8"))
    summary = report["summary"]
    assert profile["status"] == "partial"
    assert profile["observed"]["run_count"] == summary["run_count"]
    assert profile["observed"]["zero_loss_runs"] == summary["zero_acknowledged_transaction_loss_runs"]
    assert profile["observed"]["failover_rto_max_seconds"] == summary["failover_rto_max_seconds"]
    assert profile["observed"]["failback_rto_max_seconds"] == summary["failback_rto_max_seconds"]
    assert profile["observed"]["failure_domains"] == report["infrastructure"]["failure_domains_per_run"]
    assert profile["targets"]["rpo_transactions"] == 0
    assert profile["observed"]["failover_rto_max_seconds"] <= profile["targets"]["failover_rto_seconds"]
    assert profile["observed"]["failback_rto_max_seconds"] <= profile["targets"]["failback_rto_seconds"]
    assert set(profile["limitations"]) == set(report["limitations"])
