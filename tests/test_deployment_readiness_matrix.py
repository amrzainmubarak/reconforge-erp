from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
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


def test_matrix_tracks_the_current_community_compose_boundary() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    assert matrix["reviewed_on"] == "2026-08-28"
    assert len(matrix["evidence_digests"]) == 25
    community = next(edition for edition in matrix["editions"] if edition["id"] == "community")
    gate = next(gate for gate in community["gates"] if gate["id"] == "external_dependency_boundary")
    assert {
        "compose.yaml",
        "tests/test_compose_profile.py",
        "docs/adr/0662-community-compose-local-profile.md",
    } <= set(gate["evidence"])
    assert "not host firewall" in gate["boundary"]


def _copy_matrix_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    fixture_root = tmp_path / "repo"
    matrix_path = fixture_root / "docs" / "execution" / MATRIX_PATH.name
    matrix_path.parent.mkdir(parents=True)
    copied: set[str] = set()
    for edition in source["editions"]:
        for gate in edition["gates"]:
            for evidence_path in gate["evidence"]:
                if evidence_path in copied:
                    continue
                copied.add(evidence_path)
                target = fixture_root / evidence_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / evidence_path, target)
    matrix_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    return matrix_path, source


def test_runtime_reader_rejects_tampered_evidence_digest(tmp_path: Path) -> None:
    matrix_path, source = _copy_matrix_fixture(tmp_path)
    source["evidence_digests"][0]["sha256"] = "0" * 64
    matrix_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match="evidence digest mismatch"):
        load_deployment_readiness_matrix(matrix_path)


def test_runtime_reader_requires_digest_for_every_referenced_evidence(tmp_path: Path) -> None:
    matrix_path, source = _copy_matrix_fixture(tmp_path)
    source["evidence_digests"] = source["evidence_digests"][1:]
    matrix_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match="evidence digest coverage"):
        load_deployment_readiness_matrix(matrix_path)


@pytest.mark.parametrize(
    ("mutation", "error_message"),
    [
        ("malformed", "evidence digest sha256 is invalid"),
        ("duplicate", "evidence digest paths must be unique"),
        ("absolute", "evidence digest paths must be relative"),
        ("extra", "evidence digest coverage does not match"),
    ],
)
def test_runtime_reader_rejects_invalid_evidence_digest_manifest(
    tmp_path: Path,
    mutation: str,
    error_message: str,
) -> None:
    matrix_path, source = _copy_matrix_fixture(tmp_path)
    if mutation == "malformed":
        source["evidence_digests"][0]["sha256"] = "A" * 64
    elif mutation == "duplicate":
        source["evidence_digests"][1]["path"] = source["evidence_digests"][0]["path"]
    elif mutation == "absolute":
        source["evidence_digests"][0]["path"] = "C:\\outside-evidence.txt"
    else:
        source["evidence_digests"].append({"path": "extra-evidence.txt", "sha256": "0" * 64})
    matrix_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match=error_message):
        load_deployment_readiness_matrix(matrix_path)


@pytest.mark.parametrize("path", [
    "/outside-evidence.txt",
    "C:\\outside-evidence.txt",
    "C:/outside-evidence.txt",
    "C:outside-evidence.txt",
    "\\\\server\\share\\outside-evidence.txt",
    "//server/share/outside-evidence.txt",
    "\\outside-evidence.txt",
    "\\\\?\\C:\\outside-evidence.txt",
])
@pytest.mark.parametrize("location", ["gate", "digest"])
def test_runtime_reader_rejects_anchored_evidence_paths_on_every_host(
    tmp_path: Path, path: str, location: str,
) -> None:
    matrix_path, source = _copy_matrix_fixture(tmp_path)
    if location == "gate":
        source["editions"][0]["gates"][0]["evidence"][0] = path
        message = "evidence paths must be relative"
    else:
        source["evidence_digests"][0]["path"] = path
        message = "evidence digest paths must be relative"
    matrix_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match=message):
        load_deployment_readiness_matrix(matrix_path)


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


@pytest.mark.parametrize(
    ("mutation", "error_message"),
    [
        ("boolean_schema_version", "readiness matrix identity"),
        ("invalid_reviewed_on", "reviewed_on"),
        ("short_claim_boundary", "claim_boundary"),
        ("wrong_profile_command", "profile command"),
        ("short_gate_boundary", "gate boundary"),
        ("blank_gate_boundary", "gate boundary"),
    ],
)
def test_runtime_reader_matches_schema_scalar_rejections(
    tmp_path: Path,
    mutation: str,
    error_message: str,
) -> None:
    source = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    if mutation == "boolean_schema_version":
        source["schema_version"] = True
    elif mutation == "invalid_reviewed_on":
        source["reviewed_on"] = "2026-02-29"
    elif mutation == "short_claim_boundary":
        source["claim_boundary"] = "too short"
    elif mutation == "wrong_profile_command":
        source["editions"][0]["profile_command"] = "reconforge deployment profiles --edition unknown"
    elif mutation == "short_gate_boundary":
        source["editions"][0]["gates"][0]["boundary"] = "too short"
    else:
        source["editions"][0]["gates"][0]["boundary"] = " " * 20

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(source)

    path = tmp_path / f"{mutation}.yaml"
    path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    with pytest.raises(DeploymentReadinessError, match=error_message):
        load_deployment_readiness_matrix(path)
