"""CLI commands for the local bank-statement control."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reconforge.application.bank_statement_control import run_bank_statement_control_files, write_bank_statement_report
from reconforge.domain.bank_statement_control import BankStatementControlError

bank_statement_app = typer.Typer(help="Run local CAMT.053 and ledger controls.")
console = Console()


@bank_statement_app.command("control-run")
def control_run_command(
    statement_input: Annotated[Path, typer.Option("--statement-input", help="Local CAMT.053 statement file.")],
    ledger_input: Annotated[Path, typer.Option("--ledger-input", help="JSON ledger export with a records array.")],
    output: Annotated[Path, typer.Option("--output", help="Self-digesting JSON report path.")] = Path(
        "output/bank-statement-control/report.json"
    ),
    currency: Annotated[str, typer.Option("--currency", help="One registered reporting currency.")] = "USD",
    tolerance: Annotated[str, typer.Option("--tolerance", help="Exact non-negative amount tolerance.")] = "0.01",
    date_window_days: Annotated[int, typer.Option("--date-window-days", help="Maximum booking-date difference.")] = 1,
) -> None:
    """Reconcile a CAMT.053 statement to a local ledger without posting or network I/O."""

    try:
        run = run_bank_statement_control_files(
            statement_input,
            ledger_input,
            currency=currency,
            tolerance=tolerance,
            date_window_days=date_window_days,
        )
        write_bank_statement_report(run, output)
    except (BankStatementControlError, OSError) as exc:
        console.print(f"[red]Bank statement control failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Bank statement report:[/green] {output}")
    console.print(f"[green]Decision digest:[/green] {run.decision_digest}")
    console.print(f"[green]Status counts:[/green] {run.status_counts}")


__all__ = ["bank_statement_app"]
