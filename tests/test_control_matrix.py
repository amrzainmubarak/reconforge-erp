from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.control_matrix import control_matrix_frame, export_control_matrix

runner = CliRunner()


def test_control_matrix_generates_from_rule_pack(tmp_path: Path) -> None:
    matrix = control_matrix_frame("control-packs/audit-basic")
    assert not matrix.empty
    assert "control_id" in matrix.columns
    assert "rule_id" in matrix.columns
    assert "expected_evidence" in matrix.columns
    assert "owner_placeholder" in matrix.columns
    assert "frequency_placeholder" in matrix.columns
    assert "related_exceptions_placeholder" in matrix.columns
    assert "AB-001" in set(matrix["control_id"])

    artifacts = export_control_matrix("control-packs/audit-basic", tmp_path / "matrix")
    assert artifacts.workbook_path.exists()
    assert artifacts.csv_path.exists()
    assert artifacts.json_path.exists()
    assert artifacts.markdown_path.exists()
    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    assert payload["controls"][0]["control_id"].startswith("AB-")


def test_cli_control_matrix_outputs(tmp_path: Path) -> None:
    output = tmp_path / "matrix"
    result = runner.invoke(app, ["controls", "matrix", "--pack", "control-packs/audit-basic", "--output", str(output)])
    assert result.exit_code == 0
    assert (output / "control_matrix.xlsx").exists()
    assert (output / "control_matrix.csv").exists()
    assert (output / "control_matrix.json").exists()
    assert (output / "control_matrix.md").exists()


def test_control_matrix_missing_pack_handled_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["controls", "matrix", "--pack", str(tmp_path / "missing"), "--output", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "Control pack not found" in result.output
    assert "Traceback" not in result.output


def test_control_matrix_malformed_pack_handled_cleanly(tmp_path: Path) -> None:
    pack = tmp_path / "bad-pack"
    pack.mkdir()
    (pack / "pack.yml").write_text("pack_id: bad\nname: Bad\nversion: 0.1\ndescription: Bad\n", encoding="utf-8")
    (pack / "rules.yml").write_text("rules:\n  - rule_id: BAD\n", encoding="utf-8")
    result = runner.invoke(app, ["controls", "matrix", "--pack", str(pack), "--output", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "Control pack is invalid" in result.output
    assert "Traceback" not in result.output


def test_control_matrix_markdown_escapes_html(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.yml").write_text(
        'pack_id: html-pack\nname: HTML Pack\nversion: "0.1"\ndescription: Test\n',
        encoding="utf-8",
    )
    (pack / "rules.yml").write_text(
        """
rules:
  - rule_id: HTML-001
    rule_name: "<script>alert(1)</script>"
    severity: low
    entity_type: stock_move
    source_file: stock_moves.csv
    condition:
      operator: missing
      field: source_document
    message: Test
    recommended_action: "<b>Review</b>"
    risk_impact: 1
    evidence_fields: [move_id]
""",
        encoding="utf-8",
    )
    artifacts = export_control_matrix(pack, tmp_path / "out")
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in markdown
    assert "<b>Review</b>" not in markdown
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markdown
