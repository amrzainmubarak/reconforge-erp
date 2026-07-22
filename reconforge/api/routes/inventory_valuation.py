"""Authenticated routes for governed FIFO inventory valuation."""

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
from reconforge.platform.inventory_valuation import InventoryValuationService
from reconforge.platform.inventory_values import DEFAULT_LIST_LIMIT

router = APIRouter(prefix="/inventory-valuation", tags=["inventory-valuation"])
MAX_API_LIST_LIMIT = 1_000

InventoryRead = Annotated[
    LocalUser,
    Depends(
        require_any_permission(
            {"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}
        )
    ),
]
ValuationManage = Annotated[LocalUser, Depends(require_permission("inventory.valuation.manage"))]
ValuationApprove = Annotated[LocalUser, Depends(require_permission("inventory.valuation.approve"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]


class ValuationPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_code: str = Field(min_length=1, max_length=64)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    journal_code: str = Field(min_length=1, max_length=64)
    receipt_clearing_account_code: str = Field(min_length=1, max_length=64)
    cogs_account_code: str = Field(min_length=1, max_length=64)
    adjustment_account_code: str = Field(min_length=1, max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class InputCostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int = Field(ge=1, le=1_000)
    total_cost: str = Field(min_length=1, max_length=64)


class ValuationDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valuation_number: str = Field(min_length=1, max_length=64)
    movement_id: str = Field(min_length=1, max_length=160)
    policy_code: str = Field(min_length=1, max_length=64)
    valuation_date: str = Field(default="", max_length=10)
    input_costs: list[InputCostRequest] = Field(default_factory=list, max_length=1_000)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _error(code: str, exc: Exception) -> APIError:
    return APIError(status_code=400, code=code, message=str(exc))


def _list_response(
    key: str, records: list[dict[str, object]], *, limit: int, offset: int
) -> dict[str, object]:
    return {key: records, "pagination": {"limit": limit, "offset": offset, "returned": len(records)}}


@router.get("/summary")
def summary(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        result = InventoryValuationService(connection).summary(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_summary_failed", exc) from exc
    return {"summary": result.to_dict()}


@router.get("/snapshot")
def snapshot(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return InventoryValuationService(connection).snapshot(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_snapshot_failed", exc) from exc


@router.get("/policies")
def list_policies(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryValuationService(connection).list_policies(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_policies_list_failed", exc) from exc
    return _list_response("policies", records, limit=limit, offset=offset)


@router.post("/policies")
def upsert_policy(
    payload: ValuationPolicyRequest,
    current_user: ValuationManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationService(connection).upsert_policy(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_policy_save_failed", exc) from exc
    return {"policy": record}


@router.get("/documents")
def list_documents(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryValuationService(connection).list_documents(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_documents_list_failed", exc) from exc
    return _list_response("documents", records, limit=limit, offset=offset)


@router.post("/documents")
def create_document(
    payload: ValuationDocumentRequest,
    current_user: ValuationManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    values = payload.model_dump()
    try:
        record = InventoryValuationService(connection).create_document(
            **values, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_create_failed", exc) from exc
    return {"document": record}


@router.get("/documents/{document_id}")
def get_document(
    document_id: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationService(connection).get_document(
            document_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_read_failed", exc) from exc
    return {"document": record}


@router.post("/documents/{document_id}/approve")
def approve_document(
    document_id: str,
    payload: ReasonRequest,
    current_user: ValuationApprove,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationService(connection).approve_document(
            document_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_approve_failed", exc) from exc
    return {"document": record}


@router.post("/documents/{document_id}/cancel")
def cancel_document(
    document_id: str,
    payload: ReasonRequest,
    current_user: ValuationManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryValuationService(connection).cancel_document(
            document_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_cancel_failed", exc) from exc
    return {"document": record}


@router.get("/cost-layers")
def list_cost_layers(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    open_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryValuationService(connection).list_cost_layers(
            workspace=workspace,
            open_only=open_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_cost_layers_list_failed", exc) from exc
    return _list_response("cost_layers", records, limit=limit, offset=offset)
