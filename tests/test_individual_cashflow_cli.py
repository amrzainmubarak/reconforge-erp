from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reconforge.application.individual_cashflow_control import verify_individual_cashflow_report
from reconforge.cli import app


def test_individual_cashflow_cli_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "cashflow.json"
    result = CliRunner().invoke(
        app,
        [
            "individual",
            "cashflow",
            "run",
            "--transactions-input",
            "examples/individual_cashflow/transactions.json",
            "--budgets-input",
            "examples/individual_cashflow/budgets.json",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert verify_individual_cashflow_report(output)["artifact_type"] == "reconforge-individual-cashflow-control"
