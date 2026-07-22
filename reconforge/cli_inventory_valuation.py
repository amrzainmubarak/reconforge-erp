"""Focused Typer surface for local FIFO inventory valuation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from reconforge.db import DatabaseError, connect
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_valuation import InventoryValuationService

inventory_valuation_app = typer.Typer(
    help="Run governed FIFO valuation and prepare balanced Finance Core drafts."
)
DEFAULT_DB_PATH = Path("output/reconforge.db")


@contextmanager
def _service(db_path: Path) -> Iterator[InventoryValuationService]:
    connection = connect(db_path, require_exists=True)
    try:
        yield InventoryValuationService(connection)
    finally:
        connection.close()


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _fail(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1) from exc


def _input_costs(values: list[str] | None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for value in values or []:
        if len(value) > 130 or "=" not in value:
            raise PlatformError("Each --cost must use LINE=AMOUNT, for example 1=125.50.")
        line, amount = value.split("=", maxsplit=1)
        try:
            line_number = int(line)
        except ValueError as exc:
            raise PlatformError("Each --cost line number must be a positive integer.") from exc
        records.append({"line_number": line_number, "total_cost": amount})
    return records


@inventory_valuation_app.command("summary")
def summary_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print bounded valuation control counts."""

    try:
        with _service(db_path) as service:
            payload = {"summary": service.summary(workspace=workspace, actor_label=actor).to_dict()}
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)


@inventory_valuation_app.command("snapshot")
def snapshot_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print the path-free FIFO valuation snapshot."""

    try:
        with _service(db_path) as service:
            payload = service.snapshot(workspace=workspace, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)


@inventory_valuation_app.command("policy-upsert")
def policy_upsert_command(
    policy: Annotated[str, typer.Option(help="Entity-scoped valuation policy code.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    journal: Annotated[str, typer.Option(help="Finance Core journal code.")],
    receipt_clearing: Annotated[str, typer.Option("--receipt-clearing", help="Receipt clearing account code.")],
    cogs: Annotated[str, typer.Option(help="Cost-of-goods-sold account code.")],
    adjustment: Annotated[str, typer.Option(help="Inventory adjustment account code.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Create or update a governed FIFO valuation policy."""

    try:
        with _service(db_path) as service:
            record = service.upsert_policy(
                policy_code=policy,
                organization_code=organization,
                entity_code=entity,
                journal_code=journal,
                receipt_clearing_account_code=receipt_clearing,
                cogs_account_code=cogs,
                adjustment_account_code=adjustment,
                workspace=workspace,
                active=active,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"policy": record})


@inventory_valuation_app.command("policies")
def policies_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """List local FIFO policy records."""

    try:
        with _service(db_path) as service:
            records = service.list_policies(
                workspace=workspace, limit=limit, offset=offset, actor_label=actor
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"policies": records, "pagination": _pagination(limit, offset, records)})


@inventory_valuation_app.command("create")
def create_command(
    number: Annotated[str, typer.Option(help="Unique valuation number.")],
    movement_id: Annotated[str, typer.Option("--movement-id", help="Posted movement identifier.")],
    policy: Annotated[str, typer.Option(help="Entity-scoped FIFO policy code.")],
    cost: Annotated[
        list[str] | None,
        typer.Option("--cost", help="Inbound LINE=AMOUNT; repeat once for each inbound line."),
    ] = None,
    valuation_date: Annotated[
        str, typer.Option("--date", help="Optional date; must equal the movement date.")
    ] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Prepare a Draft valuation; outbound costs come from Approved FIFO layers."""

    try:
        input_costs = _input_costs(cost)
        with _service(db_path) as service:
            record = service.create_document(
                valuation_number=number,
                movement_id=movement_id,
                policy_code=policy,
                input_costs=input_costs,
                valuation_date=valuation_date,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"document": record})


@inventory_valuation_app.command("documents")
def documents_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    status: Annotated[str, typer.Option(help="Optional Draft, Approved, or Cancelled filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """List local valuation document headers."""

    try:
        with _service(db_path) as service:
            records = service.list_documents(
                workspace=workspace,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"documents": records, "pagination": _pagination(limit, offset, records)})


@inventory_valuation_app.command("show")
def show_command(
    document_id: Annotated[str, typer.Option("--document-id", help="Valuation document identifier.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print one valuation with lines and immutable FIFO consumptions."""

    try:
        with _service(db_path) as service:
            record = service.get_document(document_id, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"document": record})


def _reason_action(
    action: str, *, document_id: str, reason: str, actor: str, db_path: Path
) -> dict[str, Any]:
    with _service(db_path) as service:
        if action == "approve":
            return service.approve_document(document_id, reason=reason, actor_label=actor)
        return service.cancel_document(document_id, reason=reason, actor_label=actor)


@inventory_valuation_app.command("approve")
def approve_command(
    document_id: Annotated[str, typer.Option("--document-id", help="Valuation document identifier.")],
    reason: Annotated[str, typer.Option(help="Documented independent approval reason.")],
    actor: Annotated[str, typer.Option(help="Reviewer username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Approve FIFO valuation and create a balanced Finance Core Draft."""

    try:
        record = _reason_action(
            "approve", document_id=document_id, reason=reason, actor=actor, db_path=db_path
        )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"document": record})


@inventory_valuation_app.command("cancel")
def cancel_command(
    document_id: Annotated[str, typer.Option("--document-id", help="Valuation document identifier.")],
    reason: Annotated[str, typer.Option(help="Documented cancellation reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Cancel a Draft valuation without deleting its evidence."""

    try:
        record = _reason_action(
            "cancel", document_id=document_id, reason=reason, actor=actor, db_path=db_path
        )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"document": record})


@inventory_valuation_app.command("layers")
def layers_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    open_only: Annotated[bool, typer.Option("--open-only")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """List immutable FIFO layer origins and remaining balances."""

    try:
        with _service(db_path) as service:
            records = service.list_cost_layers(
                workspace=workspace,
                open_only=open_only,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"cost_layers": records, "pagination": _pagination(limit, offset, records)})


def _pagination(limit: int, offset: int, records: list[dict[str, Any]]) -> dict[str, int]:
    return {"limit": limit, "offset": offset, "returned": len(records)}
