import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _audit() -> dict[str, Any]:
    value = yaml.safe_load((ROOT / "docs/execution/P3_ENT_012_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_p3_ent_012_exit_audit_is_complete_bounded_and_unpublished() -> None:
    audit = _audit()
    assert audit["task_id"] == "P3-ENT-012"
    assert audit["audit_id"] == "E-234"
    assert audit["status"] == "verified"
    assert {gate["id"] for gate in audit["gates"]} == {
        "reliability_policy_and_recovery_path",
        "operational_source_and_cli_collection",
        "capacity_and_recovery_exercise",
        "postgres_reliability_parity",
        "explicit_otlp_export_runtime",
        "collector_distribution_to_file_backend",
        "ordered_incident_lifecycle",
        "production_observability_runbook_coverage",
    }
    assert all(str(gate["status"]).startswith("verified") for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])
    assert audit["runtime_evidence"]["policy"]["profile"] == "local-synthetic-single-process"
    assert audit["runtime_evidence"]["policy"]["policy_version"] == "reconforge-reliability-policy-v1"
    assert audit["runtime_evidence"]["checks"]["local_reliability_passed"] is True
    assert audit["runtime_evidence"]["checks"]["capacity_recovery_passed"] is True
    assert audit["runtime_evidence"]["checks"]["incident_lifecycle_closed"] is True
    assert audit["runtime_evidence"]["checks"]["postgres_parity_passed"] is True
    assert audit["runtime_evidence"]["checks"]["collector_runtime_passed"] is True
    assert audit["runtime_evidence"]["external_network_calls"] == 0
    assert audit["runtime_evidence"]["production_keys_secrets_or_customer_data"] == 0
    assert "no_external_collector_or_alert_manager_delivery" in audit["limitations"]
    assert "no_repeated_network_load_or_soak" in audit["limitations"]
    assert "no_durable_incident_retention" in audit["limitations"]

    enterprise = json.loads(
        (ROOT / "docs/execution/ENTERPRISE_RELIABILITY_LOCAL_DRILL_2026-07-31.json").read_text(encoding="utf-8")
    )
    capacity = json.loads(
        (ROOT / "docs/execution/RELIABILITY_CAPACITY_LOCAL_DRILL_2026-07-31.json").read_text(encoding="utf-8")
    )
    incident = json.loads(
        (ROOT / "docs/execution/RELIABILITY_INCIDENT_LOCAL_DRILL_2026-07-31.json").read_text(encoding="utf-8")
    )
    otlp = json.loads(
        (ROOT / "docs/execution/OTLP_HTTP_COLLECTOR_LOCAL_DRILL_2026-07-31.json").read_text(encoding="utf-8")
    )
    collector = json.loads(
        (ROOT / "docs/execution/OTEL_COLLECTOR_DISTRIBUTION_LOCAL_DRILL_2026-07-31.json").read_text(encoding="utf-8")
    )
    assert all(enterprise["checks"].values())
    assert all(capacity["checks"].values())
    assert all(incident["checks"].values())
    assert all(otlp["checks"].values())
    assert all(collector["checks"].values())
    assert enterprise["policy_version"] == audit["runtime_evidence"]["policy"]["policy_version"]
    assert (
        capacity["measurements"]["requests"] == audit["runtime_evidence"]["measurements"]["capacity_requests"]
    )
    assert (
        incident["measurements"]["initial_queue_depth"]
        == audit["runtime_evidence"]["measurements"]["incident_initial_queue_depth"]
    )
    assert "no_external_alert_manager_or_pager_acknowledgement" in incident["limitations"]
    assert "no_external_alert_manager_acknowledgement" in collector["limitations"]
