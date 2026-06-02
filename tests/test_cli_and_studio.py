from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.studio.app import create_studio_app

runner = CliRunner()


def test_cli_rules_validate() -> None:
    result = runner.invoke(app, ["rules", "validate", "--pack", "control-packs/audit-basic"])
    assert result.exit_code == 0
    assert "Control pack valid" in result.output


def test_cli_rules_list() -> None:
    result = runner.invoke(app, ["rules", "list", "--pack", "control-packs/audit-basic"])
    assert result.exit_code == 0
    assert "AB-001" in result.output


def test_cli_rules_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "rules",
            "run",
            "--input",
            "examples/sample_data",
            "--pack",
            "control-packs/audit-basic",
            "--output",
            str(tmp_path / "rules"),
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "rules" / "rule_results.json").exists()


def test_cli_anonymize(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["anonymize", "--input", "examples/sample_data", "--output", str(tmp_path / "anon"), "--seed", "7"],
    )
    assert result.exit_code == 0
    assert (tmp_path / "anon" / "stock_moves.csv").exists()


def test_cli_generate_synthetic(tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", "synthetic", "--rows", "25", "--output", str(tmp_path / "synthetic")])
    assert result.exit_code == 0
    assert (tmp_path / "synthetic" / "gl_entries.csv").exists()


def test_cli_benchmark_pandas(tmp_path: Path) -> None:
    runner.invoke(app, ["generate", "synthetic", "--rows", "30", "--output", str(tmp_path / "synthetic")])
    result = runner.invoke(
        app,
        ["benchmark", "--input", str(tmp_path / "synthetic"), "--engine", "pandas", "--output", str(tmp_path / "bench")],
    )
    assert result.exit_code == 0
    assert (tmp_path / "bench" / "benchmark.json").exists()


def test_studio_overview_route() -> None:
    client = TestClient(create_studio_app("examples/sample_data", "output"))
    response = client.get("/")
    assert response.status_code == 200
    assert "ReconForge Studio" in response.text


def test_studio_validation_route() -> None:
    client = TestClient(create_studio_app("examples/sample_data", "output"))
    response = client.get("/validation")
    assert response.status_code == 200
    assert "Validation Results" in response.text
