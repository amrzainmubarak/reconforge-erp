from __future__ import annotations

import hashlib
import json
import re
import tomllib
from itertools import product
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs" / "testing" / "engine-parity-matrix.v1.json"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "engine_parity_matrix.schema.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _matrix() -> dict[str, Any]:
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_engine_parity_matrix_is_closed_and_references_frozen_evidence() -> None:
    matrix = _matrix()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(matrix)
    digest_payload = dict(matrix)
    expected_digest = digest_payload.pop("matrix_digest")
    canonical = json.dumps(digest_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == expected_digest

    registry_path = ROOT / str(matrix["golden_registry"]["path"])
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["registry_version"] == matrix["golden_registry"]["registry_version"]
    assert registry["registry_digest"] == matrix["golden_registry"]["registry_digest"]
    assert all((ROOT / path).is_file() for path in matrix["required_test_files"])
    assert [profile["id"] for profile in matrix["dependency_profiles"]] == [
        "lower-bounds",
        "current-compatible-2026-07-25",
    ]
    for profile in matrix["dependency_profiles"]:
        for package in ("numpy", "pandas", "duckdb"):
            assert profile[package]["cp311_wheels"] > 0
            assert profile[package]["cp312_wheels"] > 0


def test_engine_parity_matrix_matches_declared_python_and_dependency_floors() -> None:
    matrix = _matrix()
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = pyproject["project"]
    classifiers = set(project["classifiers"])
    assert project["requires-python"] == ">=3.11"
    assert matrix["python_versions"] == ["3.11", "3.12"]
    assert {value.rsplit(" :: ", 1)[-1] for value in classifiers if value.startswith("Programming Language :: Python :: 3.")} == set(
        matrix["python_versions"]
    )

    lower = next(profile for profile in matrix["dependency_profiles"] if profile["id"] == "lower-bounds")
    assert "pandas>=2.2" in project["dependencies"]
    assert "duckdb>=1.0" in project["optional-dependencies"]["duckdb"]
    assert lower["pandas"]["version"] == "2.2.0"
    assert lower["duckdb"]["version"] == "1.0.0"


def test_ci_engine_parity_job_matches_manifest_and_forbids_skips() -> None:
    matrix = _matrix()
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job = workflow["jobs"]["engine-parity"]
    assert job["strategy"]["fail-fast"] is False
    assert "continue-on-error" not in job

    expected = {
        (
            python_version,
            profile["id"],
            profile["numpy"]["version"],
            profile["pandas"]["version"],
            profile["duckdb"]["version"],
        )
        for python_version, profile in product(matrix["python_versions"], matrix["dependency_profiles"])
    }
    configured = {
        (
            cell["python-version"],
            cell["dependency-profile"],
            cell["numpy-version"],
            cell["pandas-version"],
            cell["duckdb-version"],
        )
        for cell in job["strategy"]["matrix"]["include"]
    }
    assert configured == expected

    steps = {step["name"]: step for step in job["steps"]}
    install = steps["Install reviewed engine versions"]["run"]
    assert "--only-binary=:all:" in install
    assert 'numpy==${{ matrix.numpy-version }}' in install
    assert 'pandas==${{ matrix.pandas-version }}' in install
    assert 'duckdb==${{ matrix.duckdb-version }}' in install
    verification = steps["Verify resolved engine versions"]
    assert verification["env"] == {
        "EXPECTED_NUMPY": "${{ matrix.numpy-version }}",
        "EXPECTED_PANDAS": "${{ matrix.pandas-version }}",
        "EXPECTED_DUCKDB": "${{ matrix.duckdb-version }}",
    }
    parity_run = steps["Run no-skip engine parity contract"]["run"]
    assert all(path in parity_run for path in matrix["required_test_files"])
    assert "grep -Eq '[0-9]+ skipped'" in parity_run
    assert "exit 1" in parity_run

    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
