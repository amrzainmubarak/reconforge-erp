from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_PATH = ROOT / "docs" / "security" / "security-architecture.v2.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "security_architecture.schema.json"
RISK_REGISTER_PATH = ROOT / "docs" / "risk-register.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _by_id(records: list[dict[str, Any]], field: str = "id") -> dict[str, dict[str, Any]]:
    indexed = {record[field]: record for record in records}
    assert len(indexed) == len(records)
    return indexed


def test_security_architecture_v2_matches_closed_schema() -> None:
    architecture = _load_yaml(ARCHITECTURE_PATH)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(architecture)


def test_security_architecture_references_are_closed_and_evidence_exists() -> None:
    architecture = _load_yaml(ARCHITECTURE_PATH)
    owners = _by_id(architecture["control_owners"])
    editions = _by_id(architecture["editions"])
    data_classes = _by_id(architecture["data_classes"])
    boundaries = _by_id(architecture["trust_boundaries"])
    controls = _by_id(architecture["controls"])

    assert set(editions) == {"community-local", "team-server", "regulated"}
    assert editions["community-local"]["maturity"] == "implemented-bounded"
    assert editions["team-server"]["maturity"] == "experimental-bounded"
    assert editions["regulated"]["maturity"] == "planned-only"
    assert editions["regulated"]["enforced_controls"] == []

    for edition in editions.values():
        assert set(edition["trust_boundaries"]) <= set(boundaries)
        assert set(edition["data_classes"]) <= set(data_classes)
        assert set(edition["enforced_controls"]) <= set(controls)
    for data_class in data_classes.values():
        assert data_class["owner"] in owners
        assert set(data_class["required_controls"]) <= set(controls)
    for boundary in boundaries.values():
        assert set(boundary["assets"]) <= set(data_classes)
        assert set(boundary["controls"]) <= set(controls)
        assert any(path.startswith("tests/") for path in boundary["evidence"])
        assert any(not path.startswith("tests/") for path in boundary["evidence"])
        for relative_path in boundary["evidence"]:
            assert (ROOT / relative_path).is_file(), relative_path
    for control in controls.values():
        assert control["owner"] in owners
        assert set(control["boundaries"]) <= set(boundaries)
        assert set(control["data_classes"]) <= set(data_classes)
        for relative_path in [*control["code_evidence"], *control["test_evidence"]]:
            assert (ROOT / relative_path).is_file(), relative_path
        assert all(path.startswith("tests/") for path in control["test_evidence"])


def test_security_architecture_residual_risks_match_governance_source() -> None:
    architecture = _load_yaml(ARCHITECTURE_PATH)
    controls = _by_id(architecture["controls"])
    residual_risks = _by_id(architecture["residual_risks"], "risk_id")
    risk_register = _load_yaml(RISK_REGISTER_PATH)
    governed_risks = _by_id(risk_register["risks"])

    required_security_risks = {
        risk_id
        for risk_id, risk in governed_risks.items()
        if risk["category"]
        in {"security", "identity", "privacy", "audit", "operations"}
    }
    assert required_security_risks <= set(residual_risks)
    for risk_id, mapped in residual_risks.items():
        governed = governed_risks[risk_id]
        assert mapped["owner"] == governed["owner"]
        assert mapped["residual_risk"] == governed["residual_risk"]
        assert set(mapped["controls"]) <= set(controls)


def test_security_architecture_withholds_unsupported_security_claims() -> None:
    architecture = _load_yaml(ARCHITECTURE_PATH)
    serialized = yaml.safe_dump(architecture, sort_keys=True).casefold()

    assert "not a compliance certification" in architecture["claim_boundary"].casefold()
    assert "planned-only" in serialized
    assert "air-gap installation" in serialized
    assert "oidc" in serialized
    assert "malware scanning" in serialized
    assert "signatures" in serialized
