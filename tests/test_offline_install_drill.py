import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_offline_install_report_is_closed_and_preserves_unproven_gates() -> None:
    schema = json.loads((ROOT / "docs/schemas/offline_install_drill_report.schema.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / "docs/execution/OFFLINE_INSTALL_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["installation"]["network_mode"] == "none"
    assert report["installation"]["doctor_exit_zero"] is True
    assert report["bundle"]["entry_count"] == 60
    assert "no_offline_signature_trust" in report["limitations"]
    assert "no_physical_airgap_claim" in report["limitations"]
    assert "no_production_readiness_claim" in report["limitations"]
