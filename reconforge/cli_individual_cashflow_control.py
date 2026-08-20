"""CLI commands for local individual/freelancer cashflow controls."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reconforge.application.individual_cashflow_control import (
    run_individual_cashflow_control_files,
    write_individual_cashflow_report,
)
from reconforge.domain.individual_cashflow_control import IndividualCashflowControlError

individual_cashflow_app = typer.Typer(help="Run local individual and freelancer cashflow controls.")
console = Console()


@individual_cashflow_app.command("run")
def run_command(
    transactions_input: Annotated[Path, typer.Option("--transactions-input", help="Local transaction JSON export.")],
    budgets_input: Annotated[
        Path | None, typer.Option("--budgets-input", help="Optional local budget JSON export.")
    ] = None,
    output: Annotated[Path, typer.Option("--output", help="Self-digesting JSON report path.")] = Path(
        "output/individual-cashflow/report.json"
    ),
    currency: Annotated[str, typer.Option("--currency", help="One reporting currency.")] = "USD",
) -> None:
    """Control exact income and expenses against optional category budgets without posting."""

    try:
        run = run_individual_cashflow_control_files(transactions_input, budgets_input, currency=currency)
        write_individual_cashflow_report(run, output)
    except (IndividualCashflowControlError, OSError) as exc:
        console.print(f"[red]Individual cashflow control failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Individual cashflow report:[/green] {output}")
    console.print(f"[green]Decision digest:[/green] {run.decision_digest}")
    console.print(f"[green]Status counts:[/green] {run.status_counts}")


__all__ = ["individual_cashflow_app"]
