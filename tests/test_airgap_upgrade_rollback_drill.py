import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_airgap_upgrade_report_is_closed_and_requires_exact_rollback() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/airgap_upgrade_rollback_drill_report.schema.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (ROOT / "docs/execution/AIRGAP_UPGRADE_ROLLBACK_DOCKER_DRILL_2026-07-30.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["runtime"]["network_mode"] == "none"
    assert report["verification"]["cutover_verified"] is True
    assert report["verification"]["rollback_exact"] is True
    assert report["verification"]["rollback_sha256"]
