"""Authenticated routes for the local inventory-control ledger."""

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
        result = InventoryCoreService(connection).summary(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_summary_failed", exc) from exc
    return {"summary": result.to_dict()}


@router.get("/snapshot")
def snapshot(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return InventoryCoreService(connection).snapshot(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_snapshot_failed", exc) from exc


@router.get("/units")
def list_uoms(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryCoreService(connection).list_uoms(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_units_list_failed", exc) from exc
    return _list_response("units_of_measure", records, limit=limit, offset=offset)


@router.post("/units")
def upsert_uom(
    payload: UomRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).upsert_uom(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_unit_save_failed", exc) from exc
    return {"unit_of_measure": record}


@router.get("/items")
def list_items(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryCoreService(connection).list_items(
            workspace=workspace,
            organization_code=organization,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_items_list_failed", exc) from exc
    return _list_response("items", records, limit=limit, offset=offset)


@router.post("/items")
def upsert_item(
    payload: ItemRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).upsert_item(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_item_save_failed", exc) from exc
    return {"item": record}


@router.get("/warehouses")
def list_warehouses(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryCoreService(connection).list_warehouses(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_warehouses_list_failed", exc) from exc
    return _list_response("warehouses", records, limit=limit, offset=offset)


@router.post("/warehouses")
def upsert_warehouse(
    payload: WarehouseRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).upsert_warehouse(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_warehouse_save_failed", exc) from exc
    return {"warehouse": record}


@router.get("/locations")
def list_locations(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    warehouse: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryCoreService(connection).list_locations(
            workspace=workspace,
            organization_code=organization,
            warehouse_code=warehouse,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_locations_list_failed", exc) from exc
    return _list_response("locations", records, limit=limit, offset=offset)


@router.post("/locations")
def upsert_location(
    payload: LocationRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).upsert_location(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_location_save_failed", exc) from exc
    return {"location": record}


@router.get("/lots")
def list_lots(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    item: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryCoreService(connection).list_lots(
            workspace=workspace,
            organization_code=organization,
            item_code=item,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_lots_list_failed", exc) from exc
    return _list_response("lots_and_serials", records, limit=limit, offset=offset)


@router.post("/lots")
def upsert_lot(
    payload: LotRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).upsert_lot(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_lot_save_failed", exc) from exc
    return {"lot_or_serial": record}


@router.get("/movements")
def list_movements(
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    entity: str = "",
    period_id: str = "",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = InventoryCoreService(connection).list_movements(
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
    return _list_response("movements", records, limit=limit, offset=offset)


@router.post("/movements")
def create_movement(
    payload: MovementRequest,
    current_user: InventoryManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).create_movement(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_save_failed", exc) from exc
    return {"movement": record}


@router.get("/movements/{movement_id}")
def get_movement(
    movement_id: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).get_movement(movement_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_not_found", exc, status_code=404) from exc
    return {"movement": record}


@router.post("/movements/{movement_id}/post")
def post_movement(
    movement_id: str,
    payload: ReasonRequest,
    current_user: InventoryPost,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).post_movement(
            movement_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_post_failed", exc) from exc
    return {"movement": record}


@router.post("/movements/{movement_id}/void")
def void_movement(
    movement_id: str,
    payload: ReasonRequest,
    current_user: InventoryPost,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = InventoryCoreService(connection).void_movement(
            movement_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_movement_void_failed", exc) from exc
    return {"movement": record}


@router.get("/on-hand")
def on_hand(
    organization: str,
    entity: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    item: str = "",
    warehouse: str = "",
    include_zero: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        return InventoryCoreService(connection).on_hand(
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


@router.get("/control-exceptions")
def control_exceptions(
    organization: str,
    entity: str,
    current_user: InventoryRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    as_of: str = "",
) -> dict[str, object]:
    try:
        return InventoryCoreService(connection).control_exceptions(
            workspace=workspace,
            organization_code=organization,
            entity_code=entity,
            as_of=as_of,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("inventory_control_exceptions_failed", exc) from exc
