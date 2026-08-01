from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_p3_ent_011_exit_audit_is_complete_bounded_and_unpublished() -> None:
    audit = yaml.safe_load((ROOT / "docs/execution/P3_ENT_011_EXIT_AUDIT.yaml").read_text(encoding="utf-8"))
    assert audit["task_id"] == "P3-ENT-011"
    assert audit["audit_id"] == "E-220"
    assert audit["status"] == "verified"
    assert {gate["id"] for gate in audit["gates"]} == {
        "closed_local_bundle",
        "complete_dependency_mirror",
        "signed_artifact_identity",
        "same_signed_wheel_install",
        "os_no_network_enforcement",
        "local_identity_fallback",
        "encrypted_backup_restore",
        "offline_upgrade_rollback",
    }
    assert all(str(gate["status"]).startswith("verified") for gate in audit["gates"])
    assert all((ROOT / path).is_file() for gate in audit["gates"] for path in gate["evidence"])
    assert audit["runtime_evidence"]["signed_wheel_sha256"] == audit["runtime_evidence"][
        "installed_signed_wheel_sha256"
    ]
    assert audit["runtime_evidence"]["docker_network_mode"] == "none"
    assert not any(audit["publication"].values())
    assert "OCI_subject_offline_verification_blocked_by_gh_2_78_registry_resolution" in audit["limitations"]
