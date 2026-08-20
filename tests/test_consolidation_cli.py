from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from tests.test_consolidation_ownership_changes import _request as ownership_change_request
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


def test_consolidation_cli_ownership_change_emits_balanced_non_posting_result(tmp_path: Path) -> None:
    input_path = tmp_path / "ownership-change.json"
    output_path = tmp_path / "ownership-change-result.json"
    input_path.write_text(json.dumps({"request": [ownership_change_request().to_dict()]}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "consolidation",
            "ownership-change",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["posted"] is False
    assert payload["result_digest"]
    assert sum((Decimal(line["amount"]["amount"]) for line in payload["lines"]), Decimal("0")) == Decimal("0")
    assert "Ownership-change proposal written" in result.output


def test_consolidation_cli_ownership_change_rejects_unknown_fields(tmp_path: Path) -> None:
    input_path = tmp_path / "ownership-change-invalid.json"
    payload = ownership_change_request().to_dict()
    payload["unexpected"] = "reject-me"
    input_path.write_text(json.dumps({"request": [payload]}), encoding="utf-8")

    result = runner.invoke(app, ["consolidation", "ownership-change", "--input", str(input_path)])

    assert result.exit_code == 1
    assert "exactly the declared contract" in result.output


def test_consolidation_cli_ownership_change_accepts_direct_record(tmp_path: Path) -> None:
    input_path = tmp_path / "ownership-change-direct.json"
    input_path.write_text(json.dumps(ownership_change_request().to_dict()), encoding="utf-8")

    result = runner.invoke(app, ["consolidation", "ownership-change", "--input", str(input_path)])

    assert result.exit_code == 0
    assert '"posted": false' in result.output
