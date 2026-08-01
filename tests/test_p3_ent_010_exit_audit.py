import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _audit() -> dict[str, Any]:
    value = yaml.safe_load((ROOT / "docs/execution/P3_ENT_010_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_p3_ent_010_exit_audit_is_complete_bounded_and_unpublished() -> None:
    audit = _audit()
    assert audit["task_id"] == "P3-ENT-010"
    assert audit["audit_id"] == "E-230"
    assert audit["status"] == "verified"
    assert {gate["id"] for gate in audit["gates"]} == {
        "synchronous_standby_topology",
        "ha_dr_isolated_backup_restore",
        "failover_failback_fencing",
        "repeated_synchronous_runs",
        "named_failure_domain_and_cleanup",
        "measured_rpo_rto_boundaries",
    }
    assert all(str(gate["status"]).startswith("verified") for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])

    single_run = json.loads((ROOT / "docs/execution/HA_DR_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    repeated = json.loads(
        (ROOT / "docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION.json").read_text(encoding="utf-8")
    )
    assert repeated["schema_version"] == 1
    assert isinstance(single_run["schema"], str)
    assert single_run["topology"] == repeated["profile"]
    assert single_run["infrastructure"]["failure_domains"] == repeated["infrastructure"]["failure_domains_per_run"] == 1
    assert repeated["summary"]["run_count"] == 3
    assert repeated["summary"]["all_runs_passed"] is True
    assert repeated["summary"]["failover_rto_max_seconds"] <= 60.0
    assert repeated["summary"]["failback_rto_max_seconds"] <= 1.0
    assert audit["runtime_evidence"]["external_network_calls"] == 0
    assert audit["runtime_evidence"]["production_keys_secrets_or_customer_data"] == 0
    assert "single_host_not_host_loss" in audit["limitations"]
    assert "no_quorum_or_witness" in audit["limitations"]
    assert any("enterprise_ready" in limitation or "production_slo" in limitation for limitation in audit["limitations"])
