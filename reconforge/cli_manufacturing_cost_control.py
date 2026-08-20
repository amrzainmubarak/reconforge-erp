"""CLI commands for local manufacturing production-cost controls."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reconforge.application.manufacturing_cost_control import (
    run_manufacturing_cost_control_files,
    write_manufacturing_report,
)
from reconforge.domain.manufacturing_cost_control import ManufacturingControlError

manufacturing_cost_control_app = typer.Typer(help="Run local production-order cost and quantity controls.")
console = Console()


@manufacturing_cost_control_app.command("run")
def run_command(
    orders_input: Annotated[Path, typer.Option("--orders-input", help="Local production-order JSON export.")],
    issues_input: Annotated[Path, typer.Option("--issues-input", help="Local material-issue JSON export.")],
    completions_input: Annotated[Path, typer.Option("--completions-input", help="Local completion JSON export.")],
    scrap_input: Annotated[Path, typer.Option("--scrap-input", help="Local scrap-event JSON export.")],
    output: Annotated[Path, typer.Option("--output", help="Self-digesting JSON report path.")] = Path(
        "output/manufacturing-cost-control/report.json"
    ),
    currency: Annotated[str, typer.Option("--currency", help="One reporting currency.")] = "USD",
    tolerance: Annotated[str, typer.Option("--tolerance", help="Exact non-negative cost tolerance.")] = "0.01",
    max_scrap_quantity: Annotated[str, typer.Option("--max-scrap-quantity", help="Maximum allowed scrap quantity.")] = "0",
    unit: Annotated[str, typer.Option("--unit", help="Quantity unit used by the control.")] = "PCS",
) -> None:
    """Control material cost, production quantity, completion cost, and scrap without posting."""

    try:
        run = run_manufacturing_cost_control_files(
            orders_input,
            issues_input,
            completions_input,
            scrap_input,
            currency=currency,
            tolerance=tolerance,
            max_scrap_quantity=max_scrap_quantity,
            unit=unit,
        )
        write_manufacturing_report(run, output)
    except (ManufacturingControlError, OSError) as exc:
        console.print(f"[red]Manufacturing cost control failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Manufacturing report:[/green] {output}")
    console.print(f"[green]Decision digest:[/green] {run.decision_digest}")
    console.print(f"[green]Status counts:[/green] {run.status_counts}")


__all__ = ["manufacturing_cost_control_app"]
