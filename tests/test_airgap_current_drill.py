import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_current_airgap_install_recovery_upgrade_drill_is_schema_valid() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/airgap_install_recovery_upgrade_drill_report.schema.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (ROOT / "docs/execution/AIRGAP_INSTALL_RECOVERY_UPGRADE_DOCKER_DRILL_2026-08-05.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["runtime"]["network_mode"] == "none"
    assert report["installation"]["doctor_exit_zero"] is True
    assert report["identity_recovery"]["old_sessions_restored"] == 0
    assert report["upgrade_rollback"]["rollback_exact"] is True
