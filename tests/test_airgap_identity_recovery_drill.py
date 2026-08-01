import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_airgap_identity_recovery_report_is_closed_and_excludes_old_sessions() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/airgap_identity_recovery_drill_report.schema.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (ROOT / "docs/execution/AIRGAP_IDENTITY_RECOVERY_DOCKER_DRILL_2026-07-30.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["runtime"]["network_mode"] == "none"
    assert report["identity_recovery"]["local_users_restored"] == 2
    assert report["identity_recovery"]["old_sessions_restored"] == 0
    assert report["identity_recovery"]["wrong_key_rejected_atomically"] is True
