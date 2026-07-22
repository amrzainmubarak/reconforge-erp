"""Focused Typer surface for local inventory planning workflows."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from reconforge.db import DatabaseError, connect
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_planning import InventoryPlanningService

inventory_planning_app = typer.Typer(
    help="Run governed counts and deterministic local reorder controls."
)
DEFAULT_DB_PATH = Path("output/reconforge.db")


@contextmanager
def _service(db_path: Path) -> Iterator[InventoryPlanningService]:
    connection = connect(db_path, require_exists=True)
    try:
        yield InventoryPlanningService(connection)
    finally:
        connection.close()


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _fail(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1) from exc


@inventory_planning_app.command("summary")
def summary_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print bounded inventory-planning counts."""

    try:
        with _service(db_path) as service:
            payload = {"summary": service.summary(workspace=workspace, actor_label=actor).to_dict()}
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)


@inventory_planning_app.command("snapshot")
def snapshot_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print the local count-and-reorder snapshot."""

    try:
        with _service(db_path) as service:
            payload = service.snapshot(workspace=workspace, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)


@inventory_planning_app.command("counts")
def counts_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    status: Annotated[str, typer.Option(help="Optional count-status filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """List local inventory count headers."""

    try:
        with _service(db_path) as service:
            records = service.list_count_sessions(
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
            "count_sessions": records,
            "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
        }
    )


@inventory_planning_app.command("count-create")
def count_create_command(
    number: Annotated[str, typer.Option(help="Unique local count number.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    period_id: Annotated[str, typer.Option("--period-id", help="Fiscal-period identifier.")],
    warehouse: Annotated[str, typer.Option(help="Warehouse code.")],
    location: Annotated[str, typer.Option(help="Internal location code.")],
    count_date: Annotated[str, typer.Option("--date", help="Count date in YYYY-MM-DD format.")],
    description: Annotated[str, typer.Option(help="Count description.")] = "Inventory count",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Create a Draft physical-count session."""

    try:
        with _service(db_path) as service:
            record = service.create_count_session(
                count_number=number,
                organization_code=organization,
                entity_code=entity,
                period_id=period_id,
                warehouse_code=warehouse,
                location_code=location,
                count_date=count_date,
                description=description,
                workspace=workspace,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


@inventory_planning_app.command("count-show")
def count_show_command(
    session_id: Annotated[str, typer.Option("--session-id", help="Count-session identifier.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print one inventory count with exact snapshot and result lines."""

    try:
        with _service(db_path) as service:
            record = service.get_count_session(session_id, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


@inventory_planning_app.command("count-start")
def count_start_command(
    session_id: Annotated[str, typer.Option("--session-id", help="Count-session identifier.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Freeze the current Posted location balance as count lines."""

    try:
        with _service(db_path) as service:
            record = service.start_count_session(session_id, actor_label=actor)
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


@inventory_planning_app.command("count-record")
def count_record_command(
    session_id: Annotated[str, typer.Option("--session-id", help="Count-session identifier.")],
    line_id: Annotated[str, typer.Option("--line-id", help="Count-line identifier.")],
    quantity: Annotated[str, typer.Option(help="Exact non-negative counted quantity.")],
    note: Annotated[str, typer.Option(help="Optional count note.")] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Record an exact quantity while a session is Counting."""

    try:
        with _service(db_path) as service:
            record = service.record_counted_quantity(
                session_id,
                line_id,
                counted_quantity=quantity,
                note=note,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


def _count_reason_action(
    action: str,
    *,
    session_id: str,
    reason: str,
    actor: str,
    db_path: Path,
) -> dict[str, Any]:
    with _service(db_path) as service:
        if action == "submit":
            return service.submit_count_session(session_id, reason=reason, actor_label=actor)
        if action == "approve":
            return service.approve_count_session(session_id, reason=reason, actor_label=actor)
        return service.cancel_count_session(session_id, reason=reason, actor_label=actor)


@inventory_planning_app.command("count-submit")
def count_submit_command(
    session_id: Annotated[str, typer.Option("--session-id", help="Count-session identifier.")],
    reason: Annotated[str, typer.Option(help="Documented submission reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Submit a completed count for independent review."""

    try:
        record = _count_reason_action(
            "submit", session_id=session_id, reason=reason, actor=actor, db_path=db_path
        )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


@inventory_planning_app.command("count-approve")
def count_approve_command(
    session_id: Annotated[str, typer.Option("--session-id", help="Count-session identifier.")],
    reason: Annotated[str, typer.Option(help="Documented approval reason.")],
    actor: Annotated[str, typer.Option(help="Reviewer username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Approve a submitted count and prepare a Draft adjustment if needed."""

    try:
        record = _count_reason_action(
            "approve", session_id=session_id, reason=reason, actor=actor, db_path=db_path
        )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


@inventory_planning_app.command("count-cancel")
def count_cancel_command(
    session_id: Annotated[str, typer.Option("--session-id", help="Count-session identifier.")],
    reason: Annotated[str, typer.Option(help="Documented cancellation reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Cancel a Draft, Counting, or Submitted count."""

    try:
        record = _count_reason_action(
            "cancel", session_id=session_id, reason=reason, actor=actor, db_path=db_path
        )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"count_session": record})


@inventory_planning_app.command("reorder-upsert")
def reorder_upsert_command(
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    item: Annotated[str, typer.Option(help="Stock or consumable item code.")],
    warehouse: Annotated[str, typer.Option(help="Warehouse code.")],
    location: Annotated[str, typer.Option(help="Internal location code.")],
    minimum: Annotated[str, typer.Option(help="Exact reorder minimum.")],
    target: Annotated[str, typer.Option(help="Exact target quantity above the minimum.")],
    lead_time_days: Annotated[int, typer.Option("--lead-time-days", min=0, max=3650)] = 0,
    active: Annotated[bool, typer.Option("--active/--inactive")] = True,
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Create or update a deterministic local reorder threshold."""

    try:
        with _service(db_path) as service:
            record = service.upsert_reorder_rule(
                organization_code=organization,
                entity_code=entity,
                item_code=item,
                warehouse_code=warehouse,
                location_code=location,
                minimum_quantity=minimum,
                target_quantity=target,
                lead_time_days=lead_time_days,
                active=active,
                workspace=workspace,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json({"reorder_rule": record})


@inventory_planning_app.command("reorder-rules")
def reorder_rules_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active_only: Annotated[bool, typer.Option("--active-only")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """List local reorder rules and their current exact balances."""

    try:
        with _service(db_path) as service:
            records = service.list_reorder_rules(
                workspace=workspace,
                active_only=active_only,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(
        {
            "reorder_rules": records,
            "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
        }
    )


@inventory_planning_app.command("reorder-signals")
def reorder_signals_command(
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = DEFAULT_DB_PATH,
) -> None:
    """Print advice for active thresholds at or below their minimum."""

    try:
        with _service(db_path) as service:
            payload = service.reorder_signals(
                organization_code=organization,
                entity_code=entity,
                workspace=workspace,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
    except (DatabaseError, PlatformError) as exc:
        _fail(exc)
    _print_json(payload)
