from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS

ROOT = Path(__file__).resolve().parents[1]


def _audit() -> dict[str, Any]:
    value = yaml.safe_load(
        (ROOT / "docs/execution/P3_ENT_003_EXIT_AUDIT.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def test_p3_ent_003_exit_audit_is_evidence_complete_and_claim_bounded() -> None:
    audit = _audit()
    assert audit["task_id"] == "P3-ENT-003"
    assert audit["audit_id"] == "E-230"
    assert audit["status"] == "verified"
    assert audit["migration_head"] == "0040_postgres_webauthn_mfa"
    assert audit["migration_head"] in POSTGRES_MIGRATION_REVISIONS

    expected_gates = {
        "service_account_schema_and_permissions",
        "service_account_http_profile_and_logout",
        "machine_principal_boundaries",
        "password_reauthentication_privileged_session",
        "privileged_step_up_restrictions",
        "emergency_access_dual_control_and_review",
        "webauthn_registration_and_authentication_assertions",
        "webauthn_step_up_and_assurance_in_api",
        "migration_and_recovery",
        "external_contract_and_publication_gates",
    }
    assert {gate["id"] for gate in audit["gates"]} == expected_gates
    assert all(gate["status"].startswith("verified") and gate["evidence"] for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])

    runtime = audit["runtime_evidence"]
    assert runtime["closed_sqlite_local_gate"] == "closed_and_stable"
    assert runtime["live_postgresql_service_accounts"] == "14_passed"
    assert runtime["live_postgresql_privileged_sessions"] == "48_passed"
    assert runtime["live_postgresql_emergency_access"] == "13_passed"
    assert runtime["live_postgresql_webauthn_assertions"] == "22_passed"
    assert runtime["direct_rollback_and_reupgrade"] == "0040_to_0039_to_0040_passed"
    assert runtime["external_network_calls"] == 0
    assert runtime["production_secret_or_customer_data_handled"] == 0
    assert {
        "no_workload_identity_federation_or_hosted_service_account_federation",
        "no_production_pam_operators_or_external_assurance",
        "no_global_identity_directory_or_fully_hosted_operational_flow",
    }.issubset(audit["limitations"])
    assert not any(audit["publication"].values())


def test_p3_ent_003_failure_matrix_covers_privileged_session_threats() -> None:
    entries = _audit()["failure_matrix"]
    threats = {entry["threat"] for entry in entries}
    results = {entry["result"] for entry in entries}
    assert len(entries) >= 12
    assert "service_account_stores_plaintext_token" in threats
    assert "emergency_request_self_approval_or_missing_review" in threats
    assert "webauthn_challenge_replay_or_signature_drift" in threats
    assert "stale_or_cancelled_step_up" in threats
    assert all(result not in {"allowed", "unknown", "planned"} for result in results)
