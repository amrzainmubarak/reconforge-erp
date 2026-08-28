from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.deployment import DeploymentReadinessError, load_deployment_readiness_matrix

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


def test_runtime_reader_produces_stable_digest_and_selects_one_edition() -> None:
    matrix = load_deployment_readiness_matrix(MATRIX_PATH)
    selected = matrix.select("regulated")
    assert len(selected) == 1
    assert selected[0]["readiness_status"] == "open"
    assert len(matrix.digest) == 64
    assert matrix.digest == load_deployment_readiness_matrix(MATRIX_PATH).digest


def test_readiness_cli_is_offline_and_rejects_unknown_edition() -> None:
    result = CliRunner().invoke(app, ["deployment", "readiness", "--edition", "regulated"])
    assert result.exit_code == 0
    assert "matrix_digest" in result.stdout
    assert "external_calls" in result.stdout
    assert "open" in result.stdout

    invalid = CliRunner().invoke(app, ["deployment", "readiness", "--edition", "global"])
    assert invalid.exit_code == 1
    assert "deployment edition is unsupported" in invalid.stdout


def test_runtime_reader_rejects_missing_matrix() -> None:
    with pytest.raises(DeploymentReadinessError):
        load_deployment_readiness_matrix(ROOT / "docs" / "execution" / "missing.yaml")
