"""CLI commands for the bounded retail POS settlement control."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reconforge.application.retail_settlement import (
    run_retail_settlement_files,
    write_retail_settlement_report,
)
from reconforge.domain.retail_settlement import RetailSettlementError

retail_settlement_app = typer.Typer(help="Run local POS-to-processor settlement controls.")
console = Console()


@retail_settlement_app.command("settlement-run")
def settlement_run_command(
    pos_input: Annotated[Path, typer.Option("--pos-input", help="JSON export containing POS batches.")],
    settlement_input: Annotated[
        Path, typer.Option("--settlement-input", help="JSON export containing processor settlements.")
    ],
    output: Annotated[Path, typer.Option("--output", help="Self-digesting JSON report path.")] = Path(
        "output/retail-settlement/report.json"
    ),
    currency: Annotated[str, typer.Option("--currency", help="One registered reporting currency.")] = "USD",
    tolerance: Annotated[str, typer.Option("--tolerance", help="Exact non-negative amount tolerance.")] = "0.01",
) -> None:
    """Reconcile exported POS batches without posting or network I/O."""

    try:
        run = run_retail_settlement_files(
            pos_input,
            settlement_input,
            currency=currency,
            tolerance=tolerance,
        )
        write_retail_settlement_report(run, output)
    except (RetailSettlementError, OSError) as exc:
        console.print(f"[red]Retail settlement failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Retail settlement report:[/green] {output}")
    console.print(f"[green]Decision digest:[/green] {run.decision_digest}")
    console.print(f"[green]Status counts:[/green] {run.status_counts}")


__all__ = ["retail_settlement_app"]
