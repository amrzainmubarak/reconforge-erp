from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs" / "execution" / "DEPLOYMENT_READINESS_MATRIX.v1.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "deployment_readiness_matrix.v1.schema.json"


def test_deployment_readiness_matrix_is_closed_and_path_bound() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(matrix)

    assert {edition["id"] for edition in matrix["editions"]} == {"community", "team", "enterprise", "regulated"}
    required_gates = set(matrix["required_gates"])
    for edition in matrix["editions"]:
        gates = {gate["id"]: gate for gate in edition["gates"]}
        assert set(gates) == required_gates
        assert edition["readiness_status"] != "verified"
        for gate in edition["gates"]:
            for evidence_path in gate["evidence"]:
                assert (ROOT / evidence_path).is_file(), evidence_path
            if gate["status"] == "open":
                assert gate["evidence"] == [] or gate["boundary"]


def test_matrix_preserves_unresolved_regulated_key_and_failure_domain_gates() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    regulated = next(edition for edition in matrix["editions"] if edition["id"] == "regulated")
    gates = {gate["id"]: gate for gate in regulated["gates"]}
    assert regulated["readiness_status"] == "open"
    assert gates["customer_managed_keys"]["status"] == "open"
    assert gates["failure_domain_and_dr"]["status"] == "open"
