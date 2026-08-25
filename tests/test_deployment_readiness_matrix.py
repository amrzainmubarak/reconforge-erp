from __future__ import annotations

import json
from copy import deepcopy
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


def test_runtime_reader_requires_evidence_for_verified_gates_and_boundaries_for_all_gates(
    tmp_path: Path,
) -> None:
    source = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    verified_without_evidence = deepcopy(source)
    for edition in verified_without_evidence["editions"]:
        for gate in edition["gates"]:
            gate["evidence"] = []
    verified_path = tmp_path / "verified-without-evidence.yaml"
    verified_path.write_text(yaml.safe_dump(verified_without_evidence, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match="verified_scoped gates require evidence"):
        load_deployment_readiness_matrix(verified_path)

    unbounded_gate = deepcopy(source)
    for edition in unbounded_gate["editions"]:
        for gate in edition["gates"]:
            gate["status"] = "partial"
            gate["evidence"] = []
    unbounded_gate["editions"][0]["gates"][0]["boundary"] = ""
    unbounded_path = tmp_path / "unbounded-gate.yaml"
    unbounded_path.write_text(yaml.safe_dump(unbounded_gate, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match="gate boundary"):
        load_deployment_readiness_matrix(unbounded_path)
