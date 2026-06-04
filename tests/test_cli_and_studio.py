from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pandas as pd
from fastapi.routing import APIRoute
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.close import write_close_checklist
from reconforge.studio.app import create_studio_app

runner = CliRunner()


def _render_studio_route(path: str) -> str:
    studio = create_studio_app("examples/sample_data", "output")
    for route in studio.routes:
        if isinstance(route, APIRoute) and route.path == path:
            endpoint = cast(Callable[[], str], route.endpoint)
            return endpoint()
    raise AssertionError(f"Studio route not found: {path}")


def _render_studio_route_with_output(path: str, output: Path) -> str:
    studio = create_studio_app("examples/sample_data", output)
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


def test_studio_close_route_reads_local_checklist(tmp_path: Path) -> None:
    write_close_checklist(tmp_path / "close")
    html = _render_studio_route_with_output("/close", tmp_path)
    assert "Close Checklist" in html
    assert "CLOSE-001" in html


def test_studio_variance_route_reads_local_report(tmp_path: Path) -> None:
    variance_dir = tmp_path / "variance"
    variance_dir.mkdir()
    pd.DataFrame([{"metric": "exception_count", "amount_variance": 2, "threshold_flag": True}]).to_csv(
        variance_dir / "variance_analysis.csv",
        index=False,
    )
    html = _render_studio_route_with_output("/variance", tmp_path)
    assert "Variance Analysis" in html
    assert "exception_count" in html


def test_studio_control_matrix_route_reads_local_report(tmp_path: Path) -> None:
    matrix_dir = tmp_path / "control_matrix"
    matrix_dir.mkdir()
    pd.DataFrame([{"control_id": "AB-001", "expected_evidence": "move_id"}]).to_csv(matrix_dir / "control_matrix.csv", index=False)
    html = _render_studio_route_with_output("/control-matrix", tmp_path)
    assert "Control Matrix" in html
    assert "AB-001" in html


def test_studio_new_pages_escape_local_report_values(tmp_path: Path) -> None:
    matrix_dir = tmp_path / "control_matrix"
    matrix_dir.mkdir()
    pd.DataFrame([{"control_id": "<script>alert(1)</script>", "expected_evidence": "<b>move</b>"}]).to_csv(
        matrix_dir / "control_matrix.csv",
        index=False,
    )
    html = _render_studio_route_with_output("/control-matrix", tmp_path)
    assert "<script>alert(1)</script>" not in html
    assert "<b>move</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
