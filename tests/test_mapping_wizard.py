from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app

runner = CliRunner()


def test_mappings_inspect_detects_available_columns(tmp_path: Path) -> None:
    output = tmp_path / "mapping"
    result = runner.invoke(
        app,
        [
            "mappings",
            "inspect",
            "--input",
            "examples/sample_data",
            "--pack",
            "control-packs/odoo-inventory-valuation",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads((output / "mapping_report.json").read_text(encoding="utf-8"))
    stock = next(dataset for dataset in payload["datasets"] if dataset["dataset"] == "stock_moves.csv")
    assert stock["input_file"] == "stock_moves.csv"
    assert stock["matched_fields"]["move_id"] == "move_id"
    assert payload["summary"]["matched_fields"] > 0


def test_mappings_wizard_reports_missing_required_fields_and_suggestions(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "stock_moves.csv").write_text("move,date,source_doc,material,total_cost\n1,2026-01-01,SO-1,P-1,10\n", encoding="utf-8")
    output = tmp_path / "mapping"
    result = runner.invoke(
        app,
        [
            "mappings",
            "wizard",
            "--input",
            str(input_dir),
            "--pack",
            "control-packs/sap-mb51-fagll03",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads((output / "mapping_report.json").read_text(encoding="utf-8"))
    stock = next(dataset for dataset in payload["datasets"] if dataset["dataset"] == "stock_moves.csv")
    assert "move_id" in stock["missing_required_fields"]
    assert stock["matched_fields"]["product_code"] == "material"
    assert any(suggestion["target_field"] == "move_id" for suggestion in stock["suggestions"])


def test_mappings_inspect_handles_empty_folder_safely(tmp_path: Path) -> None:
    input_dir = tmp_path / "empty"
    input_dir.mkdir()
    output = tmp_path / "mapping"
    result = runner.invoke(
        app,
        [
            "mappings",
            "inspect",
            "--input",
            str(input_dir),
            "--pack",
            "control-packs/odoo-inventory-valuation",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert "files scanned" in result.output
    report = (output / "mapping_report.md").read_text(encoding="utf-8")
    assert "No CSV/XLSX files found" in report


def test_mappings_inspect_handles_malformed_csv_gracefully(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "stock_moves.csv").write_bytes(b'a,b\n"unterminated')
    output = tmp_path / "mapping"
    result = runner.invoke(
        app,
        [
            "mappings",
            "inspect",
            "--input",
            str(input_dir),
            "--pack",
            "control-packs/odoo-inventory-valuation",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads((output / "mapping_report.json").read_text(encoding="utf-8"))
    assert payload["summary"]["files_with_errors"] == 1
