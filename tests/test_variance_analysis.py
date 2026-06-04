from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.variance import analyze_variance, load_summary_metrics

runner = CliRunner()


def _write_management_summary(path: Path, exception_count: int, unmatched_stock: float) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "management_pack.json").write_text(
        json.dumps(
            {
                "executive_summary": [
                    {"metric": "exception_count", "value": exception_count},
                    {"metric": "unmatched_stock_amount", "value": unmatched_stock},
                ],
                "control_value_summary": [{"metric": "review_completion_rate_pct", "value": 50}],
            },
        ),
        encoding="utf-8",
    )


def test_variance_analysis_compares_summary_metrics(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    current = tmp_path / "feb"
    _write_management_summary(previous, exception_count=10, unmatched_stock=100)
    _write_management_summary(current, exception_count=15, unmatched_stock=80)

    artifacts = analyze_variance(current, previous, tmp_path / "variance", percent_threshold=20)
    assert artifacts.workbook_path.exists()
    assert artifacts.csv_path.exists()
    assert artifacts.json_path.exists()
    assert artifacts.html_path.exists()
    assert artifacts.markdown_path.exists()

    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    rows = {row["metric"]: row for row in payload["variances"]}
    assert rows["executive_summary.exception_count"]["amount_variance"] == 5
    assert rows["executive_summary.exception_count"]["percentage_variance"] == 50
    assert rows["executive_summary.exception_count"]["threshold_flag"] is True


def test_cli_variance_analysis_outputs(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    current = tmp_path / "feb"
    output = tmp_path / "variance"
    _write_management_summary(previous, exception_count=10, unmatched_stock=100)
    _write_management_summary(current, exception_count=12, unmatched_stock=105)
    result = runner.invoke(
        app,
        [
            "analyze",
            "variance",
            "--current",
            str(current),
            "--previous",
            str(previous),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert (output / "variance_analysis.json").exists()
    assert (output / "variance_analysis.html").exists()


def test_variance_missing_input_handled_cleanly(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    _write_management_summary(previous, exception_count=10, unmatched_stock=100)
    result = runner.invoke(
        app,
        ["analyze", "variance", "--current", str(tmp_path / "missing"), "--previous", str(previous), "--output", str(tmp_path / "out")],
    )
    assert result.exit_code == 1
    assert "Summary folder not found" in result.output
    assert "Traceback" not in result.output


def test_variance_malformed_summary_has_safe_error(tmp_path: Path) -> None:
    current = tmp_path / "current"
    previous = tmp_path / "previous"
    current.mkdir()
    previous.mkdir()
    (current / "management_pack.json").write_text("{bad json", encoding="utf-8")
    (previous / "management_pack.json").write_text("{bad json", encoding="utf-8")
    result = runner.invoke(
        app,
        ["analyze", "variance", "--current", str(current), "--previous", str(previous), "--output", str(tmp_path / "out")],
    )
    assert result.exit_code == 1
    assert "No summary metrics found" in result.output


def test_variance_loads_summary_csv(tmp_path: Path) -> None:
    period = tmp_path / "period"
    period.mkdir()
    (period / "stock_gl_summary.csv").write_text("metric,count\nexceptions,3\n", encoding="utf-8")
    metrics = load_summary_metrics(period)
    assert metrics["stock_gl_summary.exceptions"] == 3
