from __future__ import annotations

import json
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


def _write_recon_as_code_fixture(path: Path, *, tolerance: str = "0.00") -> Path:
    path.write_text(
        f"""
schema_version: "1.0.0"
reconciliation_id: "cli_bank_to_gl"
title: "CLI synthetic bank to GL"
sources:
  - name: "bank"
    required_columns: ["id", "amount", "date", "reference", "currency"]
    identifier_column: "id"
  - name: "ledger"
    required_columns: ["id", "amount", "date", "reference", "currency"]
    identifier_column: "id"
canonical_mapping:
  id: "record_id"
  amount: "amount"
matching_strategies:
  - name: "exact-match"
    strategy_type: "exact_1to1"
    amount_tolerance: "{tolerance}"
evidence_requirements:
  - id: "decision-lineage"
    node_types: ["source_record", "match_decision"]
test_cases:
  - id: "exact-pair"
    strategy: "exact-match"
    left_records:
      - {{id: "L1", amount: "10.00", date: "2026-01-01", reference: "A", currency: "USD"}}
    right_records:
      - {{id: "R1", amount: "10.00", date: "2026-01-01", reference: "A", currency: "USD"}}
    expected_result: "exact-pair"
expected_results:
  exact-pair:
    matched_count: 1
    unmatched_left_count: 0
    unmatched_right_count: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


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


def test_cli_reconciliation_as_code_validate_lint_test_simulate_and_diff(tmp_path: Path) -> None:
    baseline = _write_recon_as_code_fixture(tmp_path / "baseline.yaml")
    candidate = _write_recon_as_code_fixture(tmp_path / "candidate.yaml", tolerance="0.01")

    validated = runner.invoke(app, ["rules", "recon-as-code", "validate", "--file", str(baseline)])
    linted = runner.invoke(app, ["rules", "recon-as-code", "lint", "--file", str(baseline)])
    tested = runner.invoke(app, ["rules", "recon-as-code", "test", "--file", str(baseline)])
    simulated = runner.invoke(app, ["rules", "recon-as-code", "simulate", "--file", str(baseline)])
    diffed = runner.invoke(
        app,
        ["rules", "recon-as-code", "diff", "--left", str(baseline), "--right", str(candidate)],
    )
    explained = runner.invoke(app, ["rules", "recon-as-code", "explain", "--file", str(baseline)])
    rollback_output = tmp_path / "rolled-back.yaml"
    rolled_back = runner.invoke(
        app,
        [
            "rules",
            "recon-as-code",
            "rollback",
            "--current",
            str(candidate),
            "--to",
            str(baseline),
            "--output",
            str(rollback_output),
        ],
    )
    refused_overwrite = runner.invoke(
        app,
        [
            "rules",
            "recon-as-code",
            "rollback",
            "--current",
            str(candidate),
            "--to",
            str(baseline),
            "--output",
            str(rollback_output),
        ],
    )
    rollback_validated = runner.invoke(
        app,
        ["rules", "recon-as-code", "validate", "--file", str(rollback_output)],
    )

    assert validated.exit_code == 0
    assert len(json.loads(validated.output)["content_sha256"]) == 64
    assert linted.exit_code == 0
    assert json.loads(linted.output)["error_count"] == 0
    assert tested.exit_code == 0
    assert json.loads(tested.output)["all_passed"] is True
    assert simulated.exit_code == 0
    assert json.loads(simulated.output)["plan"]["side_effects"] == "none"
    assert diffed.exit_code == 0
    assert json.loads(diffed.output)["changes"] == [
        {
            "operation": "replace",
            "path": "$.matching_strategies[0].amount_tolerance",
            "before": "0.00",
            "after": "0.01",
        }
    ]
    assert explained.exit_code == 0
    assert json.loads(explained.output)["arbitrary_code_execution"] == "forbidden"
    assert rolled_back.exit_code == 0
    rollback_payload = json.loads(rolled_back.output)
    assert rollback_payload["executed"] is False
    assert rollback_payload["to_content_sha256"] == json.loads(validated.output)["content_sha256"]
    assert rollback_validated.exit_code == 0
    assert json.loads(rollback_validated.output)["content_sha256"] == json.loads(validated.output)["content_sha256"]
    assert refused_overwrite.exit_code == 1
    assert "use explicit overwrite" in refused_overwrite.output


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


def test_cli_generate_synthetic_preserves_exact_rate_text_and_rejects_scientific(tmp_path: Path) -> None:
    target = tmp_path / "exact-synthetic"
    result = runner.invoke(
        app,
        [
            "generate",
            "synthetic",
            "--rows",
            "25",
            "--output",
            str(target),
            "--exception-rate",
            "0.100000000000000005",
        ],
    )
    assert result.exit_code == 0
    manifest = json.loads((target / "synthetic_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["policy"]["exception_rate"] == "0.100000000000000005"
    assert manifest["policy"]["financial_input_policy"] == "strict-financial-input-v2"

    invalid_target = tmp_path / "invalid-synthetic"
    rejected = runner.invoke(
        app,
        [
            "generate",
            "synthetic",
            "--rows",
            "25",
            "--output",
            str(invalid_target),
            "--exception-rate",
            "1e-2",
        ],
    )
    assert rejected.exit_code == 1
    assert "exception_rate must be a plain decimal between 0 and 1" in rejected.output
    assert "1e-2" not in rejected.output
    assert not invalid_target.exists()


def test_cli_benchmark_pandas(tmp_path: Path) -> None:
    runner.invoke(app, ["generate", "synthetic", "--rows", "30", "--output", str(tmp_path / "synthetic")])
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--input",
            str(tmp_path / "synthetic"),
            "--engine",
            "pandas",
            "--output",
            str(tmp_path / "bench"),
        ],
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
    pd.DataFrame([{"control_id": "AB-001", "expected_evidence": "move_id"}]).to_csv(
        matrix_dir / "control_matrix.csv", index=False
    )
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
