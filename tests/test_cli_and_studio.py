from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from fastapi.routing import APIRoute
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.studio.app import create_studio_app

runner = CliRunner()


def _render_studio_route(path: str) -> str:
    studio = create_studio_app("examples/sample_data", "output")
    for route in studio.routes:
        if isinstance(route, APIRoute) and route.path == path:
            endpoint = cast(Callable[[], str], route.endpoint)
            return endpoint()
    raise AssertionError(f"Studio route not found: {path}")


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
    assert "ReconForge Studio" in _render_studio_route("/")


def test_studio_validation_route() -> None:
    assert "Validation Results" in _render_studio_route("/validation")
