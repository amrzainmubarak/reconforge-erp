"""Authenticated routes for governed inventory counts and reorder advice."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_planning import InventoryPlanningService
from reconforge.platform.inventory_values import DEFAULT_LIST_LIMIT

router = APIRouter(prefix="/inventory-planning", tags=["inventory-planning"])
MAX_API_LIST_LIMIT = 1_000

InventoryRead = Annotated[
    LocalUser,
    Depends(
        require_any_permission(
            {
                "inventory.read",
                "inventory.count.manage",
                "inventory.count.approve",
                "inventory.reorder.manage",
            }
        )
    ),
]
CountManage = Annotated[LocalUser, Depends(require_permission("inventory.count.manage"))]
CountApprove = Annotated[LocalUser, Depends(require_permission("inventory.count.approve"))]
CountCancel = Annotated[
    LocalUser,
    Depends(require_any_permission({"inventory.count.manage", "inventory.count.approve"})),
]
ReorderManage = Annotated[LocalUser, Depends(require_permission("inventory.reorder.manage"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]


class CountSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count_number: str = Field(min_length=1, max_length=60)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    warehouse_code: str = Field(min_length=1, max_length=64)
    location_code: str = Field(min_length=1, max_length=64)
    count_date: str = Field(min_length=10, max_length=10)
    description: str = Field(default="Inventory count", max_length=500)
    workspace: str = Field(default="default", min_length=1, max_length=160)


class CountQuantityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counted_quantity: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=500)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class ReorderRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    item_code: str = Field(min_length=1, max_length=64)
    warehouse_code: str = Field(min_length=1, max_length=64)
    location_code: str = Field(min_length=1, max_length=64)
    minimum_quantity: str = Field(min_length=1, max_length=64)
    target_quantity: str = Field(min_length=1, max_length=64)
    lead_time_days: int = Field(default=0, ge=0, le=3650)
    active: bool = True
    workspace: str = Field(default="default", min_length=1, max_length=160)


def _error(code: str, exc: Exception, *, status_code: int = 400) -> APIError:
    return APIError(status_code=status_code, code=code, message=str(exc))


def _list_response(
    key: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {key: records, "pagination": {"limit": limit, "offset": offset, "returned": len(records)}}


@router.get("/summary")
def summary(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        result = InventoryPlanningService(connection).summary(
            workspace=workspace,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_planning_summary_failed", exc) from exc
    return {"summary": result.to_dict()}


@router.get("/snapshot")
def snapshot(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return InventoryPlanningService(connection).snapshot(
            workspace=workspace,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_planning_snapshot_failed", exc) from exc


@router.get("/counts")
def list_count_sessions(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryPlanningService(connection).list_count_sessions(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_counts_list_failed", exc) from exc
    return _list_response("count_sessions", records, limit=limit, offset=offset)


@router.post("/counts")
def create_count_session(
    payload: CountSessionRequest,
    current_user: CountManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).create_count_session(
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_create_failed", exc) from exc
    return {"count_session": record}


@router.get("/counts/{session_id}")
def get_count_session(
    session_id: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).get_count_session(
            session_id,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_not_found", exc, status_code=404) from exc
    return {"count_session": record}


@router.post("/counts/{session_id}/start")
def start_count_session(
    session_id: str,
    current_user: CountManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).start_count_session(
            session_id,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_start_failed", exc) from exc
    return {"count_session": record}


@router.post("/counts/{session_id}/lines/{line_id}")
def record_counted_quantity(
    session_id: str,
    line_id: str,
    payload: CountQuantityRequest,
    current_user: CountManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).record_counted_quantity(
            session_id,
            line_id,
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_quantity_failed", exc) from exc
    return {"count_session": record}


@router.post("/counts/{session_id}/submit")
def submit_count_session(
    session_id: str,
    payload: ReasonRequest,
    current_user: CountManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).submit_count_session(
            session_id,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_submit_failed", exc) from exc
    return {"count_session": record}


@router.post("/counts/{session_id}/approve")
def approve_count_session(
    session_id: str,
    payload: ReasonRequest,
    current_user: CountApprove,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).approve_count_session(
            session_id,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_approve_failed", exc) from exc
    return {"count_session": record}


@router.post("/counts/{session_id}/cancel")
def cancel_count_session(
    session_id: str,
    payload: ReasonRequest,
    current_user: CountCancel,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).cancel_count_session(
            session_id,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_cancel_failed", exc) from exc
    return {"count_session": record}


@router.get("/reorder-rules")
def list_reorder_rules(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryPlanningService(connection).list_reorder_rules(
            workspace=workspace,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_reorder_rules_list_failed", exc) from exc
    return _list_response("reorder_rules", records, limit=limit, offset=offset)


@router.post("/reorder-rules")
def upsert_reorder_rule(
    payload: ReorderRuleRequest,
    current_user: ReorderManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryPlanningService(connection).upsert_reorder_rule(
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_reorder_rule_save_failed", exc) from exc
    return {"reorder_rule": record}


@router.get("/reorder-signals")
def reorder_signals(
    organization: str,
    entity: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        return InventoryPlanningService(connection).reorder_signals(
            workspace=workspace,
            organization_code=organization,
            entity_code=entity,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_reorder_signals_failed", exc) from exc
