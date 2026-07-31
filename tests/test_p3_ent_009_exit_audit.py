from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_p3_ent_009_exit_audit_is_complete_bounded_and_unpublished() -> None:
    audit = yaml.safe_load((ROOT / "docs/execution/P3_ENT_009_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert audit["task_id"] == "P3-ENT-009"
    assert audit["audit_id"] == "E-212"
    assert audit["status"] == "verified"
    assert {gate["id"] for gate in audit["gates"]} == {
        "closed_supported_matrix", "application_upgrade", "sqlite_upgrade", "postgres_upgrade",
        "object_catalog_upgrade", "configuration_upgrade", "signed_pack_upgrade",
        "five_resource_composition", "reverse_rollback_and_uncertain_isolation",
    }
    assert all(str(gate["status"]).startswith("verified") for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])
    matrix = yaml.safe_load((ROOT / "docs/operations/upgrade-supported-versions.v1.json").read_text(encoding="utf-8"))
    assert matrix["release_state"] == "supported"
    assert all(transition["status"] == "verified" for transition in matrix["transitions"])
    assert audit["runtime_evidence"]["production_keys_secrets_or_customer_data"] == 0
    assert not any(audit["publication"].values())
    assert "no_zero_downtime_or_distributed_atomic_cutover_claim" in audit["limitations"]
    assert "no_compliance_certification_external_assurance_or_enterprise_ready_claim" in audit["limitations"]
