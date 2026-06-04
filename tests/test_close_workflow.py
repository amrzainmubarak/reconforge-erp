from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.close_workflow import (
    close_summary_frame,
    export_close_report,
    load_close_checklist,
    update_close_task_status,
    write_close_checklist,
)

runner = CliRunner()


def test_close_init_load_and_update_status(tmp_path: Path) -> None:
    output = tmp_path / "close"
    path = write_close_checklist(output)
    assert path.exists()
    checklist = load_close_checklist(output)
    assert checklist["version"] == 1
    assert checklist["tasks"][0]["task_id"] == "CLOSE-001"
    assert "task_name" in checklist["tasks"][0]
    assert "category" in checklist["tasks"][0]

    task = update_close_task_status(output, task_id="CLOSE-001", status="Complete", owner="Finance Controller", note="Reviewed")
    assert task["status"] == "Complete"
    assert task["owner"] == "Finance Controller"
    summary = close_summary_frame(load_close_checklist(output))
    completion = summary[summary["metric"].eq("completion_rate_pct")].iloc[0]["value"]
    assert float(completion) > 0


def test_cli_close_workflow_outputs(tmp_path: Path) -> None:
    close_dir = tmp_path / "close"
    report_dir = tmp_path / "close_report"
    init_result = runner.invoke(app, ["close", "init", "--output", str(close_dir)])
    assert init_result.exit_code == 0
    set_result = runner.invoke(
        app,
        [
            "close",
            "set-status",
            "--input",
            str(close_dir),
            "--task-id",
            "CLOSE-001",
            "--status",
            "Complete",
            "--owner",
            "Finance Controller",
            "--note",
            "Reviewed",
        ],
    )
    assert set_result.exit_code == 0
    list_result = runner.invoke(app, ["close", "list", "--input", str(close_dir)])
    assert list_result.exit_code == 0
    assert "Complete" in list_result.output

    report_result = runner.invoke(app, ["close", "report", "--input", str(close_dir), "--output", str(report_dir)])
    assert report_result.exit_code == 0
    assert (report_dir / "close_report.html").exists()
    assert (report_dir / "close_report.xlsx").exists()
    assert (report_dir / "close_report.csv").exists()
    assert (report_dir / "close_summary.md").exists()


def test_close_rejects_invalid_status(tmp_path: Path) -> None:
    close_dir = tmp_path / "close"
    write_close_checklist(close_dir)
    result = runner.invoke(
        app,
        ["close", "set-status", "--input", str(close_dir), "--task-id", "CLOSE-001", "--status", "Done"],
    )
    assert result.exit_code == 1
    assert "Invalid close status" in result.output


def test_close_malformed_json_handled_cleanly(tmp_path: Path) -> None:
    close_dir = tmp_path / "close"
    close_dir.mkdir()
    (close_dir / "close_checklist.json").write_text("{bad json", encoding="utf-8")
    result = runner.invoke(app, ["close", "list", "--input", str(close_dir)])
    assert result.exit_code == 1
    assert "Close checklist JSON could not be parsed." in result.output
    assert "Traceback" not in result.output


def test_close_report_escapes_html_values(tmp_path: Path) -> None:
    close_dir = tmp_path / "close"
    write_close_checklist(close_dir)
    payload = json.loads((close_dir / "close_checklist.json").read_text(encoding="utf-8"))
    payload["tasks"][0]["task_name"] = "<script>alert(1)</script>"
    payload["tasks"][0]["note"] = "<b>reviewed</b>"
    (close_dir / "close_checklist.json").write_text(json.dumps(payload), encoding="utf-8")

    artifacts = export_close_report(close_dir, tmp_path / "report")
    html = artifacts.html_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "<b>reviewed</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;reviewed&lt;/b&gt;" in html


def test_close_template_yaml_supported(tmp_path: Path) -> None:
    template = tmp_path / "template.yml"
    template.write_text(
        """
tasks:
  - task_id: CLOSE-X
    task_name: Template task
    category: Review
    status: In Progress
""",
        encoding="utf-8",
    )
    path = write_close_checklist(tmp_path / "close", template_path=template)
    checklist = load_close_checklist(path)
    assert checklist["tasks"][0]["task_id"] == "CLOSE-X"
    assert checklist["tasks"][0]["task_name"] == "Template task"
    assert checklist["tasks"][0]["category"] == "Review"
    assert checklist["tasks"][0]["status"] == "In Progress"


def test_close_template_accepts_legacy_title_field(tmp_path: Path) -> None:
    template = tmp_path / "template.yml"
    template.write_text(
        """
tasks:
  - task_id: CLOSE-LEGACY
    title: Legacy title
    status: Not Started
""",
        encoding="utf-8",
    )
    path = write_close_checklist(tmp_path / "close", template_path=template)
    checklist = load_close_checklist(path)
    assert checklist["tasks"][0]["task_name"] == "Legacy title"
