from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _audit() -> dict[str, Any]:
    value = yaml.safe_load((ROOT / "docs/execution/P3_ENT_007_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_p3_ent_007_exit_audit_has_every_contract_and_bounded_claim() -> None:
    audit = _audit()
    assert audit["task_id"] == "P3-ENT-007"
    assert audit["audit_id"] == "E-209"
    assert audit["status"] == "verified"
    assert {gate["id"] for gate in audit["gates"]} == {
        "versioned_closed_manifests",
        "truthful_builtin_classification",
        "read_only_default",
        "data_only_signature_and_trust",
        "no_arbitrary_code_loading",
        "local_synthetic_conformance",
        "secret_reference_and_non_disclosure",
        "exact_https_egress_and_ssrf",
        "rate_and_bounded_retry",
        "cursor_and_idempotent_replay",
        "durable_checkpoint_and_crash_resume",
        "threat_model_and_operator_boundaries",
    }
    assert all(str(gate["status"]).startswith("verified") for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])
    assert {
        "no_live_vendor_connector_or_provider_interoperability",
        "sap_and_odoo_are_export_profiles_only",
        "no_production_secret_vault_or_persistent_trust_administration",
        "no_executable_external_connector_installation",
        "rate_limit_state_is_process_local_not_distributed",
        "no_external_security_assurance_ha_dr_compliance_certification_or_enterprise_ready_claim",
    }.issubset(audit["limitations"])
    assert audit["runtime_evidence"]["external_network_calls"] == 0
    assert audit["runtime_evidence"]["production_secrets_or_customer_data"] == 0
    assert not any(audit["publication"].values())


def test_p3_ent_007_failure_matrix_covers_required_hostile_paths() -> None:
    entries = _audit()["failure_matrix"]
    assert len(entries) >= 15
    assert all(entry["result"] not in {"allowed", "unknown", "planned"} for entry in entries)
    assert all((ROOT / entry["evidence"]).is_file() for entry in entries)
    threats = {entry["threat"] for entry in entries}
    for required in ("signature", "publisher", "write", "egress", "dns", "secret", "retry", "cursor", "idempotent", "crash", "checkpoint"):
        assert any(required in threat for threat in threats)
