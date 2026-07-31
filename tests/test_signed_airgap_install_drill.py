import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_signed_airgap_report_binds_verified_wheel_to_installed_wheel() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/signed_airgap_install_drill_report.schema.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (ROOT / "docs/execution/SIGNED_AIRGAP_INSTALL_DOCKER_DRILL_2026-07-30.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["release_identity"]["wheel_sha256"] == (
        "210e69770fe1ad55227173349ee22ca7f16e4f5270c093f12c78460c14b66f33"
    )
    assert report["signature_evidence"]["offline_provenance_verified"] is True
    assert report["installation"]["network_mode"] == "none"
    assert report["installation"]["doctor_exit_zero"] is True
