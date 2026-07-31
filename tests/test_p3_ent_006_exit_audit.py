from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _audit() -> dict[str, Any]:
    value = yaml.safe_load((ROOT / "docs/execution/P3_ENT_006_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_p3_ent_006_exit_audit_is_evidence_complete_and_claim_bounded() -> None:
    audit = _audit()
    assert audit["task_id"] == "P3-ENT-006"
    assert audit["audit_id"] == "E-207"
    assert audit["status"] == "verified"
    gates = audit["gates"]
    assert {gate["id"] for gate in gates} == {
        "browser_session_boundary",
        "live_browser_cookie_session",
        "host_bounded_same_origin_https",
        "audit_browse_and_verification_view",
        "security_center_view",
        "identity_and_session_view",
        "browser_session_revocation",
        "browser_user_status_lifecycle",
        "access_policy_view",
        "browser_access_policy_lifecycle",
        "integration_and_retention_view",
        "browser_integration_and_retention_lifecycle",
        "live_postgresql_server_authorization",
        "localization_and_automated_accessibility",
    }
    assert all(str(gate["status"]).startswith("verified") and gate["evidence"] for gate in gates)
    assert all((ROOT / path).is_file() for gate in gates for path in gate["evidence"])
    assert {
        "no_external_reverse_proxy_public_certificate_lifecycle_or_internet_facing_tls_evidence",
        "no_screen_reader_interoperability_or_accessibility_certification",
        "no_external_security_assurance",
        "no_ha_dr_or_enterprise_ready_claim",
    }.issubset(audit["limitations"])
    assert not any(audit["publication"].values())


def test_p3_ent_006_failure_matrix_covers_authority_disclosure_and_retention() -> None:
    entries = _audit()["failure_matrix"]
    assert len(entries) >= 15
    assert all(entry["result"] not in {"allowed", "unknown", "planned"} for entry in entries)
    assert all((ROOT / entry["evidence"]).is_file() for entry in entries)
    threats = {entry["threat"] for entry in entries}
    assert any("csrf" in threat or "cookie" in threat for threat in threats)
    assert any("host" in threat or "origin" in threat for threat in threats)
    assert any("disclosure" in threat or "secret" in threat for threat in threats)
    assert any("self_disable" in threat or "last_administrator" in threat for threat in threats)
    assert any("role" in threat for threat in threats)
    assert any("retention" in threat for threat in threats)
