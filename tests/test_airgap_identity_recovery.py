from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location(
    "verify_airgap_identity_recovery", ROOT / ".github/scripts/verify_airgap_identity_recovery.py"
)
assert SPEC is not None and SPEC.loader is not None
PROBE = module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def test_local_identity_encrypted_recovery_invalidates_sessions(tmp_path: Path) -> None:
    result = PROBE.run_drill(tmp_path)
    assert result["local_users_restored"] == 2
    assert result["old_sessions_restored"] == 0
    assert result["wrong_key_rejected"] is True
    assert result["audit_chain_valid"] is True
    assert result["credential_material_in_audit"] is False
    assert result["restored_schema_version"] == result["runtime_schema_version"]
