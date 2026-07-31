"""Typer surface for exact local FIFO valuation reversals."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from reconforge.db import DatabaseError, connect
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_valuation_reversal import InventoryValuationReversalService

inventory_valuation_reversal_app = typer.Typer(
    help="Reverse Approved FIFO evidence through an explicit mirror movement and Finance Core Draft."
)
DEFAULT_DB_PATH = Path("output/reconforge.db")


@contextmanager
def _service(db_path: Path) -> Iterator[InventoryValuationReversalService]:
    connection = connect(db_path, require_exists=True)
    try:
        yield InventoryValuationReversalService(connection)
    finally:
        connection.close()


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _fail(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1) from exc


@inventory_valuation_reversal_app.command("summary")
def summary_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print bounded reversal lifecycle counts."""

    try:
        with _service(db_path) as service:
            payload = {"summary": service.summary(workspace=workspace, actor_label=actor).to_dict()}
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)


@inventory_valuation_reversal_app.command("snapshot")
def snapshot_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print the path-free valuation-reversal snapshot."""

    try:
        with _service(db_path) as service:
            payload = service.snapshot(workspace=workspace, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)


@inventory_valuation_reversal_app.command("create")
def create_command(
    number: Annotated[str, typer.Option(help="Unique local reversal number.")],
    valuation_document_id: Annotated[
        str, typer.Option("--valuation-document-id", help="Approved original valuation ID.")
    ],
    movement_id: Annotated[str, typer.Option("--movement-id", help="Separately Posted exact mirror movement ID.")],
    actor: Annotated[str, typer.Option(help="Preparer username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Create a Draft linked to an exact Posted mirror movement."""

    try:
        with _service(db_path) as service:
            record = service.create_reversal(
                reversal_number=number,
                original_valuation_document_id=valuation_document_id,
                reversal_movement_id=movement_id,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"reversal": record})


@inventory_valuation_reversal_app.command("list")
def list_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    status: Annotated[str, typer.Option(help="Optional Draft, Approved, or Cancelled filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """List local valuation reversals."""

    try:
        with _service(db_path) as service:
            records = service.list_reversals(
                workspace=workspace,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(
        {
            "reversals": records,
            "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
        }
    )


@inventory_valuation_reversal_app.command("show")
def show_command(
    reversal_id: Annotated[str, typer.Option("--reversal-id", help="Valuation reversal ID.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Show one reversal with immutable layer effects."""

    try:
        with _service(db_path) as service:
            record = service.get_reversal(reversal_id, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"reversal": record})


def _reason_action(action: str, *, reversal_id: str, reason: str, actor: str, db_path: Path) -> dict[str, object]:
    with _service(db_path) as service:
        if action == "approve":
            return service.approve_reversal(reversal_id, reason=reason, actor_label=actor)
        return service.cancel_reversal(reversal_id, reason=reason, actor_label=actor)


@inventory_valuation_reversal_app.command("approve")
def approve_command(
    reversal_id: Annotated[str, typer.Option("--reversal-id", help="Draft reversal ID.")],
    reason: Annotated[str, typer.Option(help="Documented independent approval reason.")],
    actor: Annotated[str, typer.Option(help="Approver username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Approve exact layer effects and prepare a mirror Finance Core Draft."""

    try:
        record = _reason_action("approve", reversal_id=reversal_id, reason=reason, actor=actor, db_path=db_path)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"reversal": record})


@inventory_valuation_reversal_app.command("cancel")
def cancel_command(
    reversal_id: Annotated[str, typer.Option("--reversal-id", help="Draft reversal ID.")],
    reason: Annotated[str, typer.Option(help="Documented cancellation reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Cancel a Draft without changing layers or finance."""

    try:
        record = _reason_action("cancel", reversal_id=reversal_id, reason=reason, actor=actor, db_path=db_path)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"reversal": record})
