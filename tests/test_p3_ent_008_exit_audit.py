from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_p3_ent_008_exit_audit_is_complete_bounded_and_unpublished() -> None:
    audit = yaml.safe_load((ROOT / "docs/execution/P3_ENT_008_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert audit["task_id"] == "P3-ENT-008"
    assert audit["audit_id"] == "E-210"
    assert audit["status"] == "verified"
    assert {gate["id"] for gate in audit["gates"]} == {
        "package_identity", "signature_and_trust", "dependency_compatibility",
        "maker_checker_approval", "immutable_install_and_upgrade", "disable_and_rollback",
        "declarative_golden_conformance", "no_arbitrary_code_loading",
    }
    assert all(str(gate["status"]).startswith("verified") for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])
    assert audit["runtime_evidence"]["external_network_calls"] == 0
    assert audit["runtime_evidence"]["production_keys_secrets_or_customer_data"] == 0
    assert not any(audit["publication"].values())
    assert "no_public_marketplace_or_external_publisher_assurance" in audit["limitations"]
    assert "no_compliance_certification_external_assurance_or_enterprise_ready_claim" in audit["limitations"]
