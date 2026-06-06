from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.db import run_migrations

runner = CliRunner()


def test_workflow_cli_transitions_init_status_transition_and_history(tmp_path: Path) -> None:
    db_path = tmp_path / "workflow_cli.db"
    run_migrations(db_path)

    transitions = runner.invoke(
        app,
        ["workflow", "transitions", "--db", str(db_path), "--object-type", "reconciliation"],
    )
    initialized = runner.invoke(
        app,
        [
            "workflow",
            "init-object",
            "--db",
            str(db_path),
            "--object-type",
            "reconciliation",
            "--object-id",
            "REC-001",
            "--status",
            "Draft",
        ],
    )
    status_before = runner.invoke(
        app,
        ["workflow", "status", "--db", str(db_path), "--object-type", "reconciliation", "--object-id", "REC-001"],
    )
    transitioned = runner.invoke(
        app,
        [
            "workflow",
            "transition",
            "--db",
            str(db_path),
            "--object-type",
            "reconciliation",
            "--object-id",
            "REC-001",
            "--to-status",
            "Prepared",
            "--actor",
            "local-cli",
            "--reason",
            "Prepared for review",
        ],
    )
    history = runner.invoke(
        app,
        ["workflow", "history", "--db", str(db_path), "--object-type", "reconciliation", "--object-id", "REC-001"],
    )

    assert transitions.exit_code == 0
    assert "Draft" in transitions.output
    assert "Prepared" in transitions.output
    assert initialized.exit_code == 0
    assert "Workflow object initialized" in initialized.output
    assert status_before.exit_code == 0
    assert "Draft" in status_before.output
    assert transitioned.exit_code == 0
    assert "Workflow transitioned" in transitioned.output
    assert "Prepared" in transitioned.output
    assert history.exit_code == 0
    assert "Prepared for review" in history.output
    assert "Traceback" not in transitions.output + initialized.output + status_before.output + transitioned.output + history.output


def test_workflow_cli_invalid_transition_has_safe_error(tmp_path: Path) -> None:
    db_path = tmp_path / "workflow_cli_bad.db"
    run_migrations(db_path)
    runner.invoke(
        app,
        [
            "workflow",
            "init-object",
            "--db",
            str(db_path),
            "--object-type",
            "reconciliation",
            "--object-id",
            "REC-001",
            "--status",
            "Draft",
        ],
    )

    result = runner.invoke(
        app,
        [
            "workflow",
            "transition",
            "--db",
            str(db_path),
            "--object-type",
            "reconciliation",
            "--object-id",
            "REC-001",
            "--to-status",
            "Reviewed",
        ],
    )

    assert result.exit_code == 1
    assert "Invalid workflow transition" in result.output
    assert "Traceback" not in result.output


def test_workflow_cli_missing_db_has_safe_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "workflow",
            "transitions",
            "--db",
            str(tmp_path / "missing.db"),
            "--object-type",
            "reconciliation",
        ],
    )

    assert result.exit_code == 1
    assert "Run 'reconforge db init' first" in result.output
    assert "Traceback" not in result.output
