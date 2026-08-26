"""Authenticated routes for governed FIFO inventory valuation."""

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
    _run,
    server_inventory_valuation_enabled,
)
from reconforge.auth.field_access import (
    project_inventory_cost_layer,
    project_inventory_valuation_document,
    project_inventory_valuation_policy,
    project_inventory_valuation_snapshot,
    project_inventory_valuation_summary,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_valuation import InventoryValuationService
from reconforge.platform.inventory_values import DEFAULT_LIST_LIMIT

router = APIRouter(prefix="/inventory-valuation", tags=["inventory-valuation"])
MAX_API_LIST_LIMIT = 1_000

InventoryRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"})),
]
ValuationManage = Annotated[LocalUser, Depends(require_permission("inventory.valuation.manage"))]
ValuationApprove = Annotated[LocalUser, Depends(require_permission("inventory.valuation.approve"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
T = TypeVar("T")


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


def _list_response(key: str, records: list[dict[str, object]], *, limit: int, offset: int) -> dict[str, object]:
    return {key: records, "pagination": {"limit": limit, "offset": offset, "returned": len(records)}}


def _project_document(record: dict[str, object]) -> dict[str, object]:
    return project_inventory_valuation_document(record).visible


def _project_documents(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_project_document(record) for record in records]


def _project_policy(record: dict[str, object]) -> dict[str, object]:
    return project_inventory_valuation_policy(record).visible


def _project_policies(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_project_policy(record) for record in records]


def _project_cost_layer(record: dict[str, object]) -> dict[str, object]:
    return project_inventory_cost_layer(record).visible


def _project_cost_layers(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_project_cost_layer(record) for record in records]


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local inventory valuation database is not configured.")
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
    operation: Callable[[PostgresInventoryValuationRepository, InventoryValuationExecutionScope], T],
    *,
    organization_code: str = "",
    entity_code: str = "",
    object_refs: tuple[tuple[InventoryValuationObject, str], ...] = (),
) -> T:
    _server_scope(request, permissions)
    return _run(
        request,
        operation,
        organization_code=organization_code,
        entity_code=entity_code,
        object_refs=object_refs,
    )


@router.get("/summary")
def summary(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        result = _server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}),
            lambda repository, scope: repository.summary(workspace=scope.workspace_id, actor_label=current_user.id),
        )
        return {"summary": project_inventory_valuation_summary(result.to_dict()).visible}
    try:
        result = InventoryValuationService(_local_connection(connection)).summary(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_summary_failed", exc) from exc
    return {"summary": project_inventory_valuation_summary(result.to_dict()).visible}


@router.get("/snapshot")
def snapshot(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return project_inventory_valuation_snapshot(_server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}),
            lambda repository, scope: repository.snapshot(workspace=scope.workspace_id, actor_label=current_user.id),
        )).visible
    try:
        result = InventoryValuationService(_local_connection(connection)).snapshot(
            workspace=workspace, actor_label=current_user.username
        )
        return project_inventory_valuation_snapshot(result).visible
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_snapshot_failed", exc) from exc


@router.get("/policies")
def list_policies(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}),
            lambda repository, scope: repository.list_policies(
                workspace=scope.workspace_id, limit=limit, offset=offset, actor_label=current_user.id
            ),
        )
        return _list_response("policies", _project_policies(records), limit=limit, offset=offset)
    try:
        records = InventoryValuationService(_local_connection(connection)).list_policies(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_policies_list_failed", exc) from exc
    return _list_response("policies", _project_policies(records), limit=limit, offset=offset)


@router.post("/policies")
def upsert_policy(
    request: Request,
    payload: ValuationPolicyRequest,
    current_user: ValuationManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        values = payload.model_dump()
        values["actor_label"] = current_user.id
        return {"policy": _project_policy(_server_call(
            request,
            frozenset({"inventory.valuation.manage"}),
            lambda repository, scope: repository.upsert_policy(
                **{
                    **values,
                    "workspace": scope.workspace_id,
                    "organization_code": scope.organization_code or payload.organization_code,
                    "entity_code": scope.entity_code or payload.entity_code,
                }
            ),
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
        ))}
    try:
        record = InventoryValuationService(_local_connection(connection)).upsert_policy(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_policy_save_failed", exc) from exc
    return {"policy": _project_policy(record)}


@router.get("/documents")
def list_documents(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}),
            lambda repository, scope: repository.list_documents(
                workspace=scope.workspace_id, status=status, limit=limit, offset=offset, actor_label=current_user.id
            ),
        )
        return _list_response("documents", _project_documents(records), limit=limit, offset=offset)
    try:
        records = InventoryValuationService(_local_connection(connection)).list_documents(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_documents_list_failed", exc) from exc
    return _list_response("documents", _project_documents(records), limit=limit, offset=offset)


@router.post("/documents")
def create_document(
    request: Request,
    payload: ValuationDocumentRequest,
    current_user: ValuationManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    values = payload.model_dump()
    if server_inventory_valuation_enabled(request):
        values["actor_label"] = current_user.id
        return {"document": _project_document(_server_call(
            request,
            frozenset({"inventory.valuation.manage"}),
            lambda repository, _scope: repository.create_document(**values),
            object_refs=(("inventory_movement", payload.movement_id),),
        ))}
    try:
        record = InventoryValuationService(_local_connection(connection)).create_document(
            **values, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_create_failed", exc) from exc
    return {"document": _project_document(record)}


@router.get("/documents/{document_id}")
def get_document(
    document_id: str,
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return {"document": _project_document(_server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}),
            lambda repository, _scope: repository.get_document(document_id, actor_label=current_user.id),
            object_refs=(("valuation_document", document_id),),
        ))}
    try:
        record = InventoryValuationService(_local_connection(connection)).get_document(
            document_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_read_failed", exc) from exc
    return {"document": _project_document(record)}


@router.post("/documents/{document_id}/approve")
def approve_document(
    document_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: ValuationApprove,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return {"document": _project_document(_server_call(
            request,
            frozenset({"inventory.valuation.approve"}),
            lambda repository, _scope: repository.approve_document(
                document_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("valuation_document", document_id),),
        ))}
    try:
        record = InventoryValuationService(_local_connection(connection)).approve_document(
            document_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_approve_failed", exc) from exc
    return {"document": _project_document(record)}


@router.post("/documents/{document_id}/cancel")
def cancel_document(
    document_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: ValuationManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        return {"document": _project_document(_server_call(
            request,
            frozenset({"inventory.valuation.manage"}),
            lambda repository, _scope: repository.cancel_document(
                document_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("valuation_document", document_id),),
        ))}
    try:
        record = InventoryValuationService(_local_connection(connection)).cancel_document(
            document_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_valuation_document_cancel_failed", exc) from exc
    return {"document": _project_document(record)}


@router.get("/cost-layers")
def list_cost_layers(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    open_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_valuation_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.approve"}),
            lambda repository, scope: repository.list_cost_layers(
                workspace=scope.workspace_id,
                open_only=open_only,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
        )
        return _list_response("cost_layers", _project_cost_layers(records), limit=limit, offset=offset)
    try:
        records = InventoryValuationService(_local_connection(connection)).list_cost_layers(
            workspace=workspace,
            open_only=open_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_cost_layers_list_failed", exc) from exc
    return _list_response("cost_layers", _project_cost_layers(records), limit=limit, offset=offset)
