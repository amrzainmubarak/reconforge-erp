"""Authenticated API for exact FIFO valuation reversals."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    get_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_valuation_reversal import InventoryValuationReversalService
from reconforge.platform.inventory_values import DEFAULT_LIST_LIMIT

router = APIRouter(
    prefix="/inventory-valuation/reversals", tags=["inventory-valuation-reversals"]
)
MAX_API_LIST_LIMIT = 1_000

ReversalRead = Annotated[
    LocalUser,
    Depends(
        require_any_permission(
            {
                "inventory.read",
                "inventory.valuation.reverse.manage",
                "inventory.valuation.reverse.approve",
            }
        )
    ),
]
ReversalManage = Annotated[
    LocalUser, Depends(require_permission("inventory.valuation.reverse.manage"))
]
ReversalApprove = Annotated[
    LocalUser, Depends(require_permission("inventory.valuation.reverse.approve"))
]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]


class ReversalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reversal_number: str = Field(min_length=1, max_length=64)
    original_valuation_document_id: str = Field(min_length=1, max_length=160)
    reversal_movement_id: str = Field(min_length=1, max_length=160)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _error(code: str, exc: Exception, *, status_code: int = 400) -> APIError:
    message = str(exc) if isinstance(exc, PlatformError) else "Local valuation reversal operation failed."
    return APIError(status_code=status_code, code=code, message=message)


def _list_response(
    records: list[dict[str, object]], *, limit: int, offset: int
) -> dict[str, object]:
    return {
        "reversals": records,
        "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
    }


@router.get("/summary")
def summary(
    current_user: ReversalRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        value = InventoryValuationReversalService(connection).summary(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_summary_failed", exc) from exc
    return {"summary": value.to_dict()}


@router.get("/snapshot")
def snapshot(
    current_user: ReversalRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return InventoryValuationReversalService(connection).snapshot(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_snapshot_failed", exc) from exc


@router.get("")
def list_reversals(
    current_user: ReversalRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryValuationReversalService(connection).list_reversals(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversals_list_failed", exc) from exc
    return _list_response(records, limit=limit, offset=offset)


@router.post("")
def create_reversal(
    payload: ReversalCreateRequest,
    current_user: ReversalManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationReversalService(connection).create_reversal(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_create_failed", exc) from exc
    return {"reversal": record}


@router.get("/{reversal_id}")
def get_reversal(
    reversal_id: str,
    current_user: ReversalRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationReversalService(connection).get_reversal(
            reversal_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_not_found", exc, status_code=404) from exc
    return {"reversal": record}


@router.post("/{reversal_id}/approve")
def approve_reversal(
    reversal_id: str,
    payload: ReasonRequest,
    current_user: ReversalApprove,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationReversalService(connection).approve_reversal(
            reversal_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_approve_failed", exc) from exc
    return {"reversal": record}


@router.post("/{reversal_id}/cancel")
def cancel_reversal(
    reversal_id: str,
    payload: ReasonRequest,
    current_user: ReversalManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationReversalService(connection).cancel_reversal(
            reversal_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_cancel_failed", exc) from exc
    return {"reversal": record}
