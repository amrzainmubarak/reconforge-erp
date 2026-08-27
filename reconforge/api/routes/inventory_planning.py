"""Authenticated routes for governed inventory counts and reorder advice."""

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
from reconforge.api.server_inventory_planning import (
    InventoryPlanningExecutionScope,
    InventoryPlanningObject,
    execute_postgres_inventory_planning,
    server_inventory_planning_enabled,
)
from reconforge.auth.field_access import (
    project_inventory_planning_session,
    project_inventory_planning_snapshot,
    project_inventory_reorder_rule,
    project_inventory_reorder_signals,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_inventory_planning import PostgresInventoryPlanningRepository
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
T = TypeVar("T")


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


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local inventory planning database is not configured.")
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
    operation: Callable[[PostgresInventoryPlanningRepository, InventoryPlanningExecutionScope], T],
    *,
    organization_code: str = "",
    entity_code: str = "",
    object_refs: tuple[tuple[InventoryPlanningObject, str], ...] = (),
) -> T:
    _server_scope(request, permissions)
    return execute_postgres_inventory_planning(
        request,
        operation,
        organization_code=organization_code,
        entity_code=entity_code,
        object_refs=object_refs,
    )


def _list_response(
    key: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {key: records, "pagination": {"limit": limit, "offset": offset, "returned": len(records)}}


def _project_sessions(values: list[dict[str, object]]) -> list[dict[str, object]]:
    return [project_inventory_planning_session(value).visible for value in values]


def _project_rules(values: list[dict[str, object]]) -> list[dict[str, object]]:
    return [project_inventory_reorder_rule(value).visible for value in values]


def _project_session(value: dict[str, object]) -> dict[str, object]:
    return project_inventory_planning_session(value).visible


def _project_rule(value: dict[str, object]) -> dict[str, object]:
    return project_inventory_reorder_rule(value).visible


@router.get("/summary")
def summary(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        result = _server_call(
            request,
            frozenset({"inventory.read", "inventory.count.manage", "inventory.count.approve", "inventory.reorder.manage"}),
            lambda repository, scope: repository.summary(workspace=scope.workspace_id, actor_label=current_user.id),
        )
        return {"summary": result.to_dict()}
    try:
        result = InventoryPlanningService(_local_connection(connection)).summary(
            workspace=workspace,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_planning_summary_failed", exc) from exc
    return {"summary": result.to_dict()}


@router.get("/snapshot")
def snapshot(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return project_inventory_planning_snapshot(
            _server_call(
                request,
                frozenset({"inventory.read", "inventory.count.manage", "inventory.count.approve", "inventory.reorder.manage"}),
                lambda repository, scope: repository.snapshot(workspace=scope.workspace_id, actor_label=current_user.id),
            )
        ).visible
    try:
        return project_inventory_planning_snapshot(
            InventoryPlanningService(_local_connection(connection)).snapshot(
                workspace=workspace,
                actor_label=current_user.username,
            )
        ).visible
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_planning_snapshot_failed", exc) from exc


@router.get("/counts")
def list_count_sessions(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.count.manage", "inventory.count.approve", "inventory.reorder.manage"}),
            lambda repository, scope: repository.list_count_sessions(
                workspace=scope.workspace_id, status=status, limit=limit, offset=offset, actor_label=current_user.id
            ),
        )
        return _list_response("count_sessions", _project_sessions(records), limit=limit, offset=offset)
    try:
        records = InventoryPlanningService(_local_connection(connection)).list_count_sessions(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_counts_list_failed", exc) from exc
    return _list_response("count_sessions", _project_sessions(records), limit=limit, offset=offset)


@router.post("/counts")
def create_count_session(
    request: Request,
    payload: CountSessionRequest,
    current_user: CountManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        values = payload.model_dump()
        values["actor_label"] = current_user.id
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.count.manage"}),
            lambda repository, scope: repository.create_count_session(
                **{**values, "workspace": scope.workspace_id, "organization_code": scope.organization_code or payload.organization_code, "entity_code": scope.entity_code or payload.entity_code}
            ),
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).create_count_session(
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_create_failed", exc) from exc
    return {"count_session": _project_session(record)}


@router.get("/counts/{session_id}")
def get_count_session(
    session_id: str,
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.read", "inventory.count.manage", "inventory.count.approve", "inventory.reorder.manage"}),
            lambda repository, _scope: repository.get_count_session(session_id, actor_label=current_user.id),
            object_refs=(("count_session", session_id),),
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).get_count_session(
            session_id,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_not_found", exc, status_code=404) from exc
    return {"count_session": _project_session(record)}


@router.post("/counts/{session_id}/start")
def start_count_session(
    session_id: str,
    request: Request,
    current_user: CountManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.count.manage"}),
            lambda repository, _scope: repository.start_count_session(session_id, actor_label=current_user.id),
            object_refs=(("count_session", session_id),),
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).start_count_session(
            session_id,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_start_failed", exc) from exc
    return {"count_session": _project_session(record)}


@router.post("/counts/{session_id}/lines/{line_id}")
def record_counted_quantity(
    session_id: str,
    line_id: str,
    request: Request,
    payload: CountQuantityRequest,
    current_user: CountManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.count.manage"}),
            lambda repository, _scope: repository.record_counted_quantity(
                session_id, line_id, **payload.model_dump(), actor_label=current_user.id
            ),
            object_refs=(("count_session", session_id),),
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).record_counted_quantity(
            session_id,
            line_id,
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_quantity_failed", exc) from exc
    return {"count_session": _project_session(record)}


@router.post("/counts/{session_id}/submit")
def submit_count_session(
    session_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: CountManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.count.manage"}),
            lambda repository, _scope: repository.submit_count_session(
                session_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("count_session", session_id),),
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).submit_count_session(
            session_id,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_submit_failed", exc) from exc
    return {"count_session": _project_session(record)}


@router.post("/counts/{session_id}/approve")
def approve_count_session(
    session_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: CountApprove,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.count.approve"}),
            lambda repository, _scope: repository.approve_count_session(
                session_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("count_session", session_id),),
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).approve_count_session(
            session_id,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_approve_failed", exc) from exc
    return {"count_session": _project_session(record)}


@router.post("/counts/{session_id}/cancel")
def cancel_count_session(
    session_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: CountCancel,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return {"count_session": _project_session(_server_call(
            request,
            frozenset({"inventory.count.manage", "inventory.count.approve"}),
            lambda repository, _scope: repository.cancel_count_session(
                session_id, reason=payload.reason, actor_label=current_user.id
            ),
            object_refs=(("count_session", session_id),),
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).cancel_count_session(
            session_id,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_count_cancel_failed", exc) from exc
    return {"count_session": _project_session(record)}


@router.get("/reorder-rules")
def list_reorder_rules(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.count.manage", "inventory.count.approve", "inventory.reorder.manage"}),
            lambda repository, scope: repository.list_reorder_rules(
                workspace=scope.workspace_id, active_only=active_only, limit=limit, offset=offset, actor_label=current_user.id
            ),
        )
        return _list_response("reorder_rules", _project_rules(records), limit=limit, offset=offset)
    try:
        records = InventoryPlanningService(_local_connection(connection)).list_reorder_rules(
            workspace=workspace,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_reorder_rules_list_failed", exc) from exc
    return _list_response("reorder_rules", _project_rules(records), limit=limit, offset=offset)


@router.post("/reorder-rules")
def upsert_reorder_rule(
    request: Request,
    payload: ReorderRuleRequest,
    current_user: ReorderManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        values = payload.model_dump()
        values["actor_label"] = current_user.id
        return {"reorder_rule": _project_rule(_server_call(
            request,
            frozenset({"inventory.reorder.manage"}),
            lambda repository, scope: repository.upsert_reorder_rule(
                **{**values, "workspace": scope.workspace_id, "organization_code": scope.organization_code or payload.organization_code, "entity_code": scope.entity_code or payload.entity_code}
            ),
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
        ))}
    try:
        record = InventoryPlanningService(_local_connection(connection)).upsert_reorder_rule(
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_reorder_rule_save_failed", exc) from exc
    return {"reorder_rule": _project_rule(record)}


@router.get("/reorder-signals")
def reorder_signals(
    organization: str,
    entity: str,
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_planning_enabled(request):
        return project_inventory_reorder_signals(
            _server_call(
                request,
                frozenset({"inventory.read", "inventory.count.manage", "inventory.count.approve", "inventory.reorder.manage"}),
                lambda repository, scope: repository.reorder_signals(
                    workspace=scope.workspace_id,
                    organization_code=scope.organization_code or organization,
                    entity_code=scope.entity_code or entity,
                    limit=limit,
                    offset=offset,
                    actor_label=current_user.id,
                ),
                organization_code=organization,
                entity_code=entity,
            )
        ).visible
    try:
        return project_inventory_reorder_signals(
            InventoryPlanningService(_local_connection(connection)).reorder_signals(
                workspace=workspace,
                organization_code=organization,
                entity_code=entity,
                limit=limit,
                offset=offset,
                actor_label=current_user.username,
            )
        ).visible
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_reorder_signals_failed", exc) from exc
