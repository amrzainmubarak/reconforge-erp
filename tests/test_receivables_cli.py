from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.db import run_migrations

runner = CliRunner()


def test_receivables_cli_help_and_customer_workflow(tmp_path: Path) -> None:
    db_path = tmp_path / "receivables-cli.db"
    run_migrations(db_path)
    help_result = runner.invoke(app, ["receivables", "--help"])
    customer_result = runner.invoke(
        app,
        [
            "receivables",
            "customer-upsert",
            "--code",
            "CUS-CLI",
            "--name",
            "Synthetic CLI Customer",
            "--currency",
            "USD",
            "--credit-limit-minor",
            "5000",
            "--db",
            str(db_path),
        ],
    )
    list_result = runner.invoke(app, ["receivables", "customers", "--db", str(db_path)])
    assert help_result.exit_code == 0
    assert "customer-upsert" in help_result.stdout
    assert customer_result.exit_code == 0
    assert list_result.exit_code == 0
    assert "No records found." not in list_result.stdout
