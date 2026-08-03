from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from tests.test_sqlite_consolidation_close import _database, _prepare

runner = CliRunner()


def test_consolidation_cli_exposes_replay_verified_run_and_management_statement(tmp_path: Path) -> None:
    db_path, connection = _database(tmp_path)
    try:
        _repository, _period, run = _prepare(connection)
    finally:
        connection.close()

    summary = runner.invoke(app, ["consolidation", "summary", "--db", str(db_path)])
    assert summary.exit_code == 0
    assert "prepared_runs" in summary.output
    assert "1" in summary.output

    runs = runner.invoke(app, ["consolidation", "runs", "--db", str(db_path)])
    assert runs.exit_code == 0
    assert str(run["id"]) in runs.output

    detail = runner.invoke(
        app,
        ["consolidation", "run", "--db", str(db_path), "--run-id", str(run["id"])],
    )
    assert detail.exit_code == 0
    assert "management_statement" in detail.output
    assert "translation_evidence" in detail.output
    assert "worksheet_result_digest" in detail.output


def test_consolidation_cli_run_is_replay_fail_closed_for_unknown_id(tmp_path: Path) -> None:
    db_path, connection = _database(tmp_path)
    connection.close()

    result = runner.invoke(
        app,
        ["consolidation", "run", "--db", str(db_path), "--run-id", "missing-run"],
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()
