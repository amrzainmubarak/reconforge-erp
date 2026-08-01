import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_offline_attestation_report_is_closed_and_preserves_oci_boundary() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/offline_attestation_drill_report.schema.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (ROOT / "docs/execution/OFFLINE_ATTESTATION_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["runtime"]["network_mode"] == "none"
    assert report["verification"]["file_provenance_subjects"] == 11
    assert report["verification"]["file_sbom_attestations"] == 3
    assert report["verification"]["offline_oci_attestations"] == 0
    assert "oci_subject_verification_requires_registry_resolution_in_gh_2_78_0" in report["limitations"]
