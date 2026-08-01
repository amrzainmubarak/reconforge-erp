import json
from pathlib import Path

import jsonschema

from reconforge.incident_response import verify_incident_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_retained_reliability_incident_drill_is_closed_and_truthful() -> None:
    report = json.loads(
        (ROOT / "docs/execution/RELIABILITY_INCIDENT_LOCAL_DRILL_2026-07-30.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/reliability_incident_drill_report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    assert all(report["checks"].values())
    assert verify_incident_manifest(report["incident"])
    assert report["incident"]["events"][1]["operator_ref"] != report["incident"]["events"][3]["operator_ref"]
    assert "no_external_alert_manager_or_pager_acknowledgement" in report["limitations"]
