"""Authenticated API for exact FIFO valuation reversals."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    enforce_server_scoped_permissions,
    get_local_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.api.server_inventory_valuation import (
    InventoryValuationExecutionScope,
    InventoryValuationObject,
    _run_reversal,
    server_inventory_valuation_enabled,
)
from reconforge.auth.field_access import (
    project_inventory_valuation_reversal,
    project_inventory_valuation_reversal_snapshot,
    project_inventory_valuation_reversal_summary,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_inventory_valuation_reversal import PostgresInventoryValuationReversalRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_valuation_reversal import InventoryValuationReversalService
from reconforge.platform.inventory_values import DEFAULT_LIST_LIMIT

router = APIRouter(prefix="/inventory-valuation/reversals", tags=["inventory-valuation-reversals"])
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
ReversalManage = Annotated[LocalUser, Depends(require_permission("inventory.valuation.reverse.manage"))]
ReversalApprove = Annotated[LocalUser, Depends(require_permission("inventory.valuation.reverse.approve"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
T = TypeVar("T")


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


def _list_response(records: list[dict[str, object]], *, limit: int, offset: int) -> dict[str, object]:
    return {
        "reversals": records,
        "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
    }


def _project_reversal(record: dict[str, object]) -> dict[str, object]:
    return project_inventory_valuation_reversal(record).visible


def _project_reversals(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_project_reversal(record) for record in records]


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local valuation reversal database is not configured.")
    return connection


def _server_scope(request: Request, permissions: frozenset[str]) -> RequestExecutionScope:
    scope = request_execution_scope(request)
    if len(permissions) == 1:
        enforce_server_scoped_permission(
            request,
            permission=next(iter(permissions)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
        )
    else:
        enforce_server_scoped_permissions(
            request,
            permissions=permissions,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
        )
    return scope


def _server_call(
    request: Request,
    permissions: frozenset[str],
    operation: Callable[
        [PostgresInventoryValuationReversalRepository, InventoryValuationExecutionScope], T
    ],
    *,
    object_refs: tuple[tuple[InventoryValuationObject, str], ...] = (),
) -> T:
    _server_scope(request, permissions)
    return _run_reversal(request, operation, object_refs=object_refs)


@router.get("/summary")
def summary(
    request: Request,
    current_user: ReversalRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        value = _server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.reverse.manage", "inventory.valuation.reverse.approve"}),
            lambda repository, scope: repository.summary(workspace=scope.workspace_id, actor_label=current_user.id),
        )
        return {"summary": project_inventory_valuation_reversal_summary(value.to_dict()).visible}
    try:
        value = InventoryValuationReversalService(_local_connection(connection)).summary(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_summary_failed", exc) from exc
    return {"summary": project_inventory_valuation_reversal_summary(value.to_dict()).visible}


@router.get("/snapshot")
def snapshot(
    request: Request,
    current_user: ReversalRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return project_inventory_valuation_reversal_snapshot(_server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.reverse.manage", "inventory.valuation.reverse.approve"}),
            lambda repository, scope: repository.snapshot(workspace=scope.workspace_id, actor_label=current_user.id),
        )).visible
    try:
        result = InventoryValuationReversalService(_local_connection(connection)).snapshot(
            workspace=workspace, actor_label=current_user.username
        )
        return project_inventory_valuation_reversal_snapshot(result).visible
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_snapshot_failed", exc) from exc


@router.get("")
def list_reversals(
    request: Request,
    current_user: ReversalRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.reverse.manage", "inventory.valuation.reverse.approve"}),
            lambda repository, scope: repository.list_reversals(
                workspace=scope.workspace_id, status=status, limit=limit, offset=offset, actor_label=current_user.id
            ),
        )
        return _list_response(_project_reversals(records), limit=limit, offset=offset)
    try:
        records = InventoryValuationReversalService(_local_connection(connection)).list_reversals(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversals_list_failed", exc) from exc
    return _list_response(_project_reversals(records), limit=limit, offset=offset)


@router.post("")
def create_reversal(
    request: Request,
    payload: ReversalCreateRequest,
    current_user: ReversalManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        values = payload.model_dump()
        values["actor_label"] = current_user.id
        return {"reversal": _project_reversal(_server_call(
            request,
            frozenset({"inventory.valuation.reverse.manage"}),
            lambda repository, _scope: repository.create_reversal(**values),
            object_refs=(
                ("valuation_document", payload.original_valuation_document_id),
                ("inventory_movement", payload.reversal_movement_id),
            ),
        ))}
    try:
        record = InventoryValuationReversalService(_local_connection(connection)).create_reversal(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_create_failed", exc) from exc
    return {"reversal": _project_reversal(record)}


@router.get("/{reversal_id}")
def get_reversal(
    reversal_id: str,
    request: Request,
    current_user: ReversalRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return {"reversal": _project_reversal(_server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.reverse.manage", "inventory.valuation.reverse.approve"}),
            lambda repository, _scope: repository.get_reversal(reversal_id, actor_label=current_user.id),
            object_refs=(("valuation_reversal", reversal_id),),
        ))}
    try:
        record = InventoryValuationReversalService(_local_connection(connection)).get_reversal(
            reversal_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_not_found", exc, status_code=404) from exc
    return {"reversal": _project_reversal(record)}


@router.post("/{reversal_id}/approve")
def approve_reversal(
    reversal_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: ReversalApprove,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return {"reversal": _project_reversal(_server_call(
            request,
            frozenset({"inventory.valuation.reverse.approve"}),
            lambda repository, _scope: repository.approve_reversal(
                reversal_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("valuation_reversal", reversal_id),),
        ))}
    try:
        record = InventoryValuationReversalService(_local_connection(connection)).approve_reversal(
            reversal_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_approve_failed", exc) from exc
    return {"reversal": _project_reversal(record)}


@router.post("/{reversal_id}/cancel")
def cancel_reversal(
    reversal_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: ReversalManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return {"reversal": _project_reversal(_server_call(
            request,
            frozenset({"inventory.valuation.reverse.manage"}),
            lambda repository, _scope: repository.cancel_reversal(
                reversal_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("valuation_reversal", reversal_id),),
        ))}
    try:
        record = InventoryValuationReversalService(_local_connection(connection)).cancel_reversal(
            reversal_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_reversal_cancel_failed", exc) from exc
    return {"reversal": _project_reversal(record)}
