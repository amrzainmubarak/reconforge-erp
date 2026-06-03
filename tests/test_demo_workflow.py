from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app

runner = CliRunner()


def test_demo_command_completes_and_writes_expected_files(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "run", "--output", str(output)])
    assert result.exit_code == 0
    assert (output / "management_pack.xlsx").exists()
    assert (output / "executive_report.html").exists()
    assert (output / "dashboard.html").exists()
    assert (output / "evidence").exists()
    assert (output / "review_state.json").exists()
    assert (output / "review_register.xlsx").exists()
    assert (output / "summary.md").exists()
    assert (output / "client_pack" / "files_manifest.json").exists()


def test_client_pack_command_copies_available_outputs(tmp_path: Path) -> None:
    source = tmp_path / "output"
    source.mkdir()
    (source / "executive_report.html").write_text("<html>report</html>", encoding="utf-8")
    (source / "management_pack.xlsx").write_bytes(b"placeholder workbook")
    (source / "review_register.xlsx").write_bytes(b"placeholder register")
    (source / "summary.md").write_text("# Original summary\n", encoding="utf-8")
    (source / "evidence").mkdir()
    (source / "evidence" / "index.html").write_text("<html>evidence</html>", encoding="utf-8")
    target = tmp_path / "client_pack"

    result = runner.invoke(app, ["report", "client-pack", "--input", str(source), "--output", str(target)])

    assert result.exit_code == 0
    assert (target / "executive_report.html").exists()
    assert (target / "management_pack.xlsx").exists()
    assert (target / "review_register.xlsx").exists()
    assert (target / "evidence" / "index.html").exists()
    assert (target / "source_summary.md").read_text(encoding="utf-8") == "# Original summary\n"
    assert (target / "handoff_summary.md").exists()
    assert not (target / "summary.md").exists()
    assert (target / "next_steps.md").exists()
    assert (target / "data_privacy_note.md").exists()
    assert (target / "files_manifest.json").exists()
    manifest = json.loads((target / "files_manifest.json").read_text(encoding="utf-8"))
    manifest_paths = {item["path"] for item in manifest["included_files"]}
    assert "source_summary.md" in manifest_paths
    assert "handoff_summary.md" in manifest_paths


def test_client_pack_handles_missing_optional_outputs(tmp_path: Path) -> None:
    source = tmp_path / "output"
    source.mkdir()
    target = tmp_path / "client_pack"

    result = runner.invoke(app, ["report", "client-pack", "--input", str(source), "--output", str(target)])

    assert result.exit_code == 0
    assert (target / "handoff_summary.md").exists()
    assert (target / "data_privacy_note.md").exists()
    assert (target / "files_manifest.json").exists()
