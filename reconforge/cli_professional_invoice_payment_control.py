"""CLI commands for local professional invoice-to-payment controls."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reconforge.application.professional_invoice_payment_control import (
    run_professional_invoice_payment_control_files,
    write_professional_invoice_payment_report,
)
from reconforge.domain.professional_invoice_payment_control import ProfessionalInvoicePaymentError

professional_invoice_payment_app = typer.Typer(help="Run local professional invoice-to-payment controls.")
console = Console()


@professional_invoice_payment_app.command("run")
def run_command(
    invoices_input: Annotated[Path, typer.Option("--invoices-input", help="Local invoice JSON export.")],
    payments_input: Annotated[Path, typer.Option("--payments-input", help="Local payment JSON export.")],
    output: Annotated[Path, typer.Option("--output", help="Self-digesting JSON report path.")] = Path(
        "output/professional-invoice-payment/report.json"
    ),
    currency: Annotated[str, typer.Option("--currency", help="One reporting currency.")] = "USD",
    tolerance: Annotated[str, typer.Option("--tolerance", help="Exact non-negative amount tolerance.")] = "0.01",
    payment_window_days: Annotated[int, typer.Option("--payment-window-days", help="Allowed absolute days from due date.")] = 7,
) -> None:
    """Control invoice-to-payment amount, client, reference, and date bounds without posting."""

    try:
        run = run_professional_invoice_payment_control_files(
            invoices_input,
            payments_input,
            currency=currency,
            tolerance=tolerance,
            payment_window_days=payment_window_days,
        )
        write_professional_invoice_payment_report(run, output)
    except (ProfessionalInvoicePaymentError, OSError) as exc:
        console.print(f"[red]Professional invoice/payment control failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Professional invoice/payment report:[/green] {output}")
    console.print(f"[green]Decision digest:[/green] {run.decision_digest}")
    console.print(f"[green]Status counts:[/green] {run.status_counts}")


__all__ = ["professional_invoice_payment_app"]
