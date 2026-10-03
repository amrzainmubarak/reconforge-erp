"""Authenticated routes for the local inventory-control ledger."""

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
from reconforge.api.server_inventory_core import (
    InventoryOperation,
    execute_postgres_inventory,
    server_inventory_core_enabled,
)
from reconforge.auth.field_access import (
    project_inventory_control_exceptions,
    project_inventory_core_snapshot,
    project_inventory_core_summary,
    project_inventory_item,
    project_inventory_location,
    project_inventory_lot,
    project_inventory_movement,
    project_inventory_on_hand,
    project_inventory_uom,
    project_inventory_warehouse,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_core import DEFAULT_LIST_LIMIT, InventoryCoreService

router = APIRouter(prefix="/inventory", tags=["inventory"])
MAX_API_LIST_LIMIT = 1_000

InventoryRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"inventory.read", "inventory.manage", "inventory.post"})),
]
InventoryManage = Annotated[LocalUser, Depends(require_permission("inventory.manage"))]
InventoryPost = Annotated[LocalUser, Depends(require_permission("inventory.post"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
T = TypeVar("T")


class UomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uom_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    category: str = Field(default="Count", min_length=1, max_length=40)
    decimal_places: int = Field(default=0, ge=0, le=6)
    active: bool = True


class ItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    uom_code: str = Field(default="EA", min_length=1, max_length=64)
    item_type: str = Field(default="Stock", min_length=1, max_length=40)
    tracking_mode: str = Field(default="None", min_length=1, max_length=40)
    inventory_account_code: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)
    active: bool = True


class WarehouseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    organization_code: str = Field(min_length=1, max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    entity_code: str = Field(default="", max_length=64)
    active: bool = True


class LocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_code: str = Field(min_length=1, max_length=64)
    location_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    organization_code: str = Field(min_length=1, max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    parent_location_code: str = Field(default="", max_length=64)
    location_type: str = Field(default="Internal", min_length=1, max_length=40)
    allow_negative: bool = False
    active: bool = True


class LotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str = Field(min_length=1, max_length=64)
    lot_serial_code: str = Field(min_length=1, max_length=64)
    organization_code: str = Field(min_length=1, max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    manufactured_on: str = Field(default="", max_length=10)
    expires_on: str = Field(default="", max_length=10)
    active: bool = True


class MovementLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str = Field(min_length=1, max_length=64)
    quantity: str = Field(min_length=1, max_length=64)
    from_location: str = Field(default="", max_length=129)
    to_location: str = Field(default="", max_length=129)
    lot_serial_code: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)


class MovementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    movement_number: str = Field(min_length=1, max_length=64)
    movement_type: str = Field(min_length=1, max_length=40)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    movement_date: str = Field(min_length=10, max_length=10)
    description: str = Field(min_length=1, max_length=500)
    lines: list[MovementLineRequest] = Field(min_length=1, max_length=1_000)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    source_reference: str = Field(default="", max_length=160)
    source_type: str = Field(default="Manual", min_length=1, max_length=40)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _error(code: str, exc: Exception, *, status_code: int = 400) -> APIError:
    return APIError(status_code=status_code, code=code, message=str(exc))


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(
            status_code=500,
            code="local_database_not_configured",
            message="The local Inventory Core database is not configured for this request.",
        )
    return connection


def _list_response(
    key: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {key: records, "pagination": {"limit": limit, "offset": offset, "returned": len(records)}}


def _project_records(records: list[dict[str, object]], projector: Callable[[dict[str, object]], dict[str, object]]) -> list[dict[str, object]]:
    return [projector(record) for record in records]


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
    operation: InventoryOperation[T],
    *,
    organization_code: str = "",
    entity_code: str = "",
    movement_id: str | None = None,
) -> T:
    _server_scope(request, permissions)
    return execute_postgres_inventory(
        request,
        operation,
        organization_code=organization_code,
        entity_code=entity_code,
        movement_id=movement_id,
    )


@router.get("/summary")
def summary(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        result = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.summary(workspace=scope.workspace_id, actor_label=current_user.id),
        )
        return {"summary": project_inventory_core_summary(result.to_dict()).visible}
    try:
        result = InventoryCoreService(_local_connection(connection)).summary(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_summary_failed", exc) from exc
    return {"summary": project_inventory_core_summary(result.to_dict()).visible}


@router.get("/snapshot")
def snapshot(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        result = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.snapshot(workspace=scope.workspace_id, actor_label=current_user.id),
        )
        return project_inventory_core_snapshot(result).visible
    try:
        result = InventoryCoreService(_local_connection(connection)).snapshot(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_snapshot_failed", exc) from exc
    return project_inventory_core_snapshot(result).visible


@router.get("/units")
def list_uoms(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.list_uoms(
                workspace=scope.workspace_id, limit=limit, offset=offset, actor_label=current_user.id
            ),
        )
        return _list_response("units_of_measure", _project_records(records, lambda value: project_inventory_uom(value).visible), limit=limit, offset=offset)
    try:
        records = InventoryCoreService(_local_connection(connection)).list_uoms(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_units_list_failed", exc) from exc
    return _list_response("units_of_measure", _project_records(records, lambda value: project_inventory_uom(value).visible), limit=limit, offset=offset)


@router.post("/units")
def upsert_uom(
    request: Request,
    payload: UomRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        values = payload.model_dump()
        record = _server_call(
            request,
            frozenset({"inventory.manage"}),
            lambda repository, scope: repository.upsert_uom(
                **{**values, "workspace": scope.workspace_id, "actor_label": current_user.id}
            ),
        )
        return {"unit_of_measure": project_inventory_uom(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).upsert_uom(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_unit_save_failed", exc) from exc
    return {"unit_of_measure": project_inventory_uom(record).visible}


@router.get("/items")
def list_items(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.list_items(
                workspace=scope.workspace_id,
                organization_code=scope.organization_code or organization,
                active_only=active_only,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
            organization_code=organization,
        )
        return _list_response("items", _project_records(records, lambda value: project_inventory_item(value).visible), limit=limit, offset=offset)
    try:
        records = InventoryCoreService(_local_connection(connection)).list_items(
            workspace=workspace,
            organization_code=organization,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_items_list_failed", exc) from exc
    return _list_response("items", _project_records(records, lambda value: project_inventory_item(value).visible), limit=limit, offset=offset)


@router.post("/items")
def upsert_item(
    request: Request,
    payload: ItemRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        values = payload.model_dump()
        record = _server_call(
            request,
            frozenset({"inventory.manage"}),
            lambda repository, scope: repository.upsert_item(
                **{
                    **values,
                    "workspace": scope.workspace_id,
                    "organization_code": scope.organization_code or str(values["organization_code"]),
                    "actor_label": current_user.id,
                }
            ),
            organization_code=payload.organization_code,
        )
        return {"item": project_inventory_item(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).upsert_item(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_item_save_failed", exc) from exc
    return {"item": project_inventory_item(record).visible}


@router.get("/warehouses")
def list_warehouses(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.list_warehouses(
                workspace=scope.workspace_id,
                organization_code=scope.organization_code or organization,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
            organization_code=organization,
        )
        return _list_response("warehouses", _project_records(records, lambda value: project_inventory_warehouse(value).visible), limit=limit, offset=offset)
    try:
        records = InventoryCoreService(_local_connection(connection)).list_warehouses(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_warehouses_list_failed", exc) from exc
    return _list_response("warehouses", _project_records(records, lambda value: project_inventory_warehouse(value).visible), limit=limit, offset=offset)


@router.post("/warehouses")
def upsert_warehouse(
    request: Request,
    payload: WarehouseRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        values = payload.model_dump()
        record = _server_call(
            request,
            frozenset({"inventory.manage"}),
            lambda repository, scope: repository.upsert_warehouse(
                **{
                    **values,
                    "workspace": scope.workspace_id,
                    "organization_code": scope.organization_code or str(values["organization_code"]),
                    "entity_code": scope.entity_code or str(values["entity_code"]),
                    "actor_label": current_user.id,
                }
            ),
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
        )
        return {"warehouse": project_inventory_warehouse(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).upsert_warehouse(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_warehouse_save_failed", exc) from exc
    return {"warehouse": project_inventory_warehouse(record).visible}


@router.get("/locations")
def list_locations(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    warehouse: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.list_locations(
                workspace=scope.workspace_id,
                organization_code=scope.organization_code or organization,
                warehouse_code=warehouse,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
            organization_code=organization,
        )
        return _list_response("locations", _project_records(records, lambda value: project_inventory_location(value).visible), limit=limit, offset=offset)
    try:
        records = InventoryCoreService(_local_connection(connection)).list_locations(
            workspace=workspace,
            organization_code=organization,
            warehouse_code=warehouse,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_locations_list_failed", exc) from exc
    return _list_response("locations", _project_records(records, lambda value: project_inventory_location(value).visible), limit=limit, offset=offset)


@router.post("/locations")
def upsert_location(
    request: Request,
    payload: LocationRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        values = payload.model_dump()
        record = _server_call(
            request,
            frozenset({"inventory.manage"}),
            lambda repository, scope: repository.upsert_location(
                **{
                    **values,
                    "workspace": scope.workspace_id,
                    "organization_code": scope.organization_code or str(values["organization_code"]),
                    "actor_label": current_user.id,
                }
            ),
            organization_code=payload.organization_code,
        )
        return {"location": project_inventory_location(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).upsert_location(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_location_save_failed", exc) from exc
    return {"location": project_inventory_location(record).visible}


@router.get("/lots")
def list_lots(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    item: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.list_lots(
                workspace=scope.workspace_id,
                organization_code=scope.organization_code or organization,
                item_code=item,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
            organization_code=organization,
        )
        return _list_response("lots_and_serials", _project_records(records, lambda value: project_inventory_lot(value).visible), limit=limit, offset=offset)
    try:
        records = InventoryCoreService(_local_connection(connection)).list_lots(
            workspace=workspace,
            organization_code=organization,
            item_code=item,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_lots_list_failed", exc) from exc
    return _list_response("lots_and_serials", _project_records(records, lambda value: project_inventory_lot(value).visible), limit=limit, offset=offset)


@router.post("/lots")
def upsert_lot(
    request: Request,
    payload: LotRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        values = payload.model_dump()
        record = _server_call(
            request,
            frozenset({"inventory.manage"}),
            lambda repository, scope: repository.upsert_lot(
                **{
                    **values,
                    "workspace": scope.workspace_id,
                    "organization_code": scope.organization_code or str(values["organization_code"]),
                    "actor_label": current_user.id,
                }
            ),
            organization_code=payload.organization_code,
        )
        return {"lot_or_serial": project_inventory_lot(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).upsert_lot(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_lot_save_failed", exc) from exc
    return {"lot_or_serial": project_inventory_lot(record).visible}


@router.get("/movements")
def list_movements(
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    entity: str = "",
    period_id: str = "",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        records = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.list_movements(
                workspace=scope.workspace_id,
                organization_code=scope.organization_code or organization,
                entity_code=scope.entity_code or entity,
                period_id=period_id,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
            organization_code=organization,
            entity_code=entity,
        )
        return _list_response(
            "movements",
            _project_records(records, lambda value: project_inventory_movement(value).visible),
            limit=limit,
            offset=offset,
        )
    try:
        records = InventoryCoreService(_local_connection(connection)).list_movements(
            workspace=workspace,
            organization_code=organization,
            entity_code=entity,
            period_id=period_id,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movements_list_failed", exc) from exc
    return _list_response(
        "movements",
        _project_records(records, lambda value: project_inventory_movement(value).visible),
        limit=limit,
        offset=offset,
    )


@router.post("/movements")
def create_movement(
    request: Request,
    payload: MovementRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        values = payload.model_dump()
        record = _server_call(
            request,
            frozenset({"inventory.manage"}),
            lambda repository, scope: repository.create_movement(
                **{
                    **values,
                    "workspace": scope.workspace_id,
                    "organization_code": scope.organization_code or str(values["organization_code"]),
                    "entity_code": scope.entity_code or str(values["entity_code"]),
                    "actor_label": current_user.id,
                }
            ),
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
        )
        return {"movement": project_inventory_movement(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).create_movement(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_save_failed", exc) from exc
    return {"movement": project_inventory_movement(record).visible}


@router.get("/movements/{movement_id}")
def get_movement(
    movement_id: str,
    request: Request,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        record = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, _scope: repository.get_movement(movement_id, actor_label=current_user.id),
            movement_id=movement_id,
        )
        return {"movement": project_inventory_movement(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).get_movement(movement_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_not_found", exc, status_code=404) from exc
    return {"movement": project_inventory_movement(record).visible}


@router.post("/movements/{movement_id}/post")
def post_movement(
    movement_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: InventoryPost,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        record = _server_call(
            request,
            frozenset({"inventory.post"}),
            lambda repository, _scope: repository.post_movement(
                movement_id, reason=payload.reason, actor_label=current_user.id
            ),
            movement_id=movement_id,
        )
        return {"movement": project_inventory_movement(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).post_movement(
            movement_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_post_failed", exc) from exc
    return {"movement": project_inventory_movement(record).visible}


@router.post("/movements/{movement_id}/void")
def void_movement(
    movement_id: str,
    request: Request,
    payload: ReasonRequest,
    current_user: InventoryPost,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        record = _server_call(
            request,
            frozenset({"inventory.post"}),
            lambda repository, _scope: repository.void_movement(
                movement_id, reason=payload.reason, actor_label=current_user.id
            ),
            movement_id=movement_id,
        )
        return {"movement": project_inventory_movement(record).visible}
    try:
        record = InventoryCoreService(_local_connection(connection)).void_movement(
            movement_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_void_failed", exc) from exc
    return {"movement": project_inventory_movement(record).visible}


@router.get("/on-hand")
def on_hand(
    request: Request,
    organization: str,
    entity: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    item: str = "",
    warehouse: str = "",
    include_zero: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        result = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.on_hand(
                organization_code=scope.organization_code or organization,
                entity_code=scope.entity_code or entity,
                workspace=scope.workspace_id,
                item_code=item,
                warehouse_code=warehouse,
                include_zero=include_zero,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
            organization_code=organization,
            entity_code=entity,
        )
        return project_inventory_on_hand(result).visible
    try:
        result = InventoryCoreService(_local_connection(connection)).on_hand(
            workspace=workspace,
            organization_code=organization,
            entity_code=entity,
            item_code=item,
            warehouse_code=warehouse,
            include_zero=include_zero,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_on_hand_failed", exc) from exc
    return project_inventory_on_hand(result).visible


@router.get("/control-exceptions")
def control_exceptions(
    request: Request,
    organization: str,
    entity: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    as_of: str = "",
) -> dict[str, object]:
    if server_inventory_core_enabled(request):
        result = _server_call(
            request,
            frozenset({"inventory.read", "inventory.manage", "inventory.post"}),
            lambda repository, scope: repository.control_exceptions(
                organization_code=scope.organization_code or organization,
                entity_code=scope.entity_code or entity,
                workspace=scope.workspace_id,
                as_of=as_of,
                actor_label=current_user.id,
            ),
            organization_code=organization,
            entity_code=entity,
        )
        return project_inventory_control_exceptions(result).visible
    try:
        result = InventoryCoreService(_local_connection(connection)).control_exceptions(
            workspace=workspace,
            organization_code=organization,
            entity_code=entity,
            as_of=as_of,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_control_exceptions_failed", exc) from exc
    return project_inventory_control_exceptions(result).visible
