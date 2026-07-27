from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from reconforge.modules.registry import list_modules

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "docs" / "security" / "threat-model-index.v1.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "threat_model_index.schema.json"
ARCHITECTURE_PATH = ROOT / "docs" / "security" / "security-architecture.v2.yaml"
RISK_PATH = ROOT / "docs" / "risk-register.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_threat_model_index_matches_closed_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(_load_yaml(INDEX_PATH))


def test_every_active_module_has_an_exact_threat_model_entry() -> None:
    payload = _load_yaml(INDEX_PATH)
    indexed = {entry["module_id"]: entry for entry in payload["modules"]}
    registry = {descriptor.module_id: descriptor for descriptor in list_modules()}

    assert len(indexed) == len(payload["modules"])
    assert set(indexed) == set(registry)
    for module_id, descriptor in registry.items():
        entry = indexed[module_id]
        assert entry["registry_maturity"] == descriptor.maturity
        assert entry["capability_status"] == descriptor.capability_status
        assert set(entry["interfaces"]) == set(descriptor.interfaces)
        assert set(entry["module_data_classifications"]) == set(descriptor.data_classification)
        assert set(entry["module_test_evidence"]) >= set(descriptor.test_evidence)
        assert len(entry["assets"]) >= 1
        assert len(entry["actors"]) >= 1
        assert len(entry["threat_cases"]) >= 2


def test_threat_model_references_are_closed_and_evidence_exists() -> None:
    payload = _load_yaml(INDEX_PATH)
    architecture = _load_yaml(ARCHITECTURE_PATH)
    risks = _load_yaml(RISK_PATH)

    actor_ids = {entry["id"] for entry in payload["actors"]}
    threat_ids = {entry["id"] for entry in payload["threat_catalog"]}
    boundary_ids = {entry["id"] for entry in architecture["trust_boundaries"]}
    data_class_ids = {entry["id"] for entry in architecture["data_classes"]}
    control_ids = {entry["id"] for entry in architecture["controls"]}
    owner_ids = {entry["id"] for entry in architecture["control_owners"]}
    risk_ids = {entry["id"] for entry in risks["risks"]}
    used_threats: set[str] = set()

    assert len(actor_ids) == len(payload["actors"])
    assert len(threat_ids) == len(payload["threat_catalog"])
    assert payload["review_policy"]["owner"] in owner_ids
    for source_path in payload["sources"].values():
        assert (ROOT / source_path).is_file(), source_path

    for module in payload["modules"]:
        assert module["owner"] in owner_ids
        assert set(module["architecture_boundaries"]) <= boundary_ids
        assert set(module["actors"]) <= actor_ids
        assert len({asset["id"] for asset in module["assets"]}) == len(module["assets"])
        assert {asset["data_class"] for asset in module["assets"]} <= data_class_ids
        assert len({case["threat_id"] for case in module["threat_cases"]}) == len(module["threat_cases"])
        for evidence_path in module["module_test_evidence"]:
            assert (ROOT / evidence_path).is_file(), evidence_path
        for case in module["threat_cases"]:
            used_threats.add(case["threat_id"])
            assert case["threat_id"] in threat_ids
            assert set(case["controls"]) <= control_ids
            assert set(case["residual_risk_ids"]) <= risk_ids
            for evidence_path in case["test_evidence"]:
                assert (ROOT / evidence_path).is_file(), evidence_path

    assert used_threats == threat_ids


def test_threat_model_keeps_residual_and_claim_boundaries_visible() -> None:
    payload = _load_yaml(INDEX_PATH)
    boundary = payload["claim_boundary"].lower()
    assert "not a security guarantee" in boundary
    assert "not a compliance" in boundary
    assert all(module["threat_model_status"] == "evidence-bounded" for module in payload["modules"])
    assert all(module["out_of_scope"] for module in payload["modules"])
    assert all(
        any(case["status"] in {"partial", "deployment-dependent", "planned"} for case in module["threat_cases"])
        for module in payload["modules"]
    )


def test_readable_threat_model_names_every_indexed_module() -> None:
    payload = _load_yaml(INDEX_PATH)
    readable = (ROOT / "docs" / "security" / "threat-model.md").read_text(encoding="utf-8")
    for module in payload["modules"]:
        assert f"`{module['module_id']}`" in readable
