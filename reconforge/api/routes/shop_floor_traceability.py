"""FastAPI routes for Shop Floor Execution, WIP Progress, and Lot Genealogy."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.shop_floor_dispatch import (
    LotStatus,
    LotTraceabilityRecord,
    ShopFloorExecutionError,
    ShopFloorOperationStep,
    StepStatus,
    WorkOrderDispatch,
    traverse_genealogy,
    validate_step_progression,
)
from reconforge.infrastructure.postgres_shop_floor import PostgresShopFloorRepository
from reconforge.infrastructure.sqlite_shop_floor import SqliteShopFloorRepository

router = APIRouter(prefix="/manufacturing/traceability", tags=["shop-floor-traceability"])

ShopFloorRead = Annotated[LocalUser, Depends(require_any_permission({"manufacturing_execution.read", "manufacturing_execution.manage"}))]
ShopFloorManage = Annotated[LocalUser, Depends(require_permission("manufacturing_execution.manage"))]


class ParentLotConsumption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    parent_lot_id: str = Field(min_length=1, max_length=128)
    quantity_consumed_scaled: int = Field(gt=0)


class LotRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lot_id: str = Field(min_length=1, max_length=128)
    item_id: str = Field(min_length=1, max_length=128)
    batch_number: str = Field(min_length=1, max_length=128)
    quantity_scaled: int = Field(gt=0)
    scale_factor: int = Field(default=1000, gt=0)
    status: LotStatus = "active"
    notes: str = Field(default="", max_length=500)
    parent_lots: list[ParentLotConsumption] = Field(default_factory=list)


class OperationStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step_id: str = Field(min_length=1, max_length=128)
    work_order_id: str = Field(min_length=1, max_length=128)
    operation_sequence: int = Field(gt=0)
    work_center_id: str = Field(min_length=1, max_length=128)
    operator_id: str = Field(min_length=1, max_length=128)
    status: StepStatus = "pending"
    actual_run_minutes: int = Field(default=0, ge=0)
    quantity_completed_scaled: int = Field(default=0, ge=0)
    quantity_scrapped_scaled: int = Field(default=0, ge=0)
    scrap_reason_code: str = Field(default="", max_length=64)
    started_at: str = Field(default="")
    completed_at: str = Field(default="")


class WorkOrderDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dispatch_id: str = Field(min_length=1, max_length=128)
    work_order_id: str = Field(min_length=1, max_length=128)
    item_id: str = Field(min_length=1, max_length=128)
    scheduled_quantity_scaled: int = Field(gt=0)
    dispatched_lot_id: str = Field(min_length=1, max_length=128)
    dispatched_at: str = Field(min_length=1)
    steps: list[OperationStepInput] = Field(min_length=1)


class StepProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dispatch_id: str = Field(min_length=1, max_length=128)
    step: OperationStepInput


def _get_repo(request: Request) -> tuple[Any, SqliteShopFloorRepository | PostgresShopFloorRepository]:
    server_mode = bool(getattr(request.app.state, "server_mode", False))
    factory = (
        getattr(request.app.state, "postgres_finance_core_factory", None)
        or getattr(request.app.state, "postgres_identity_factory", None)
        or getattr(request.app.state, "postgres_connection_factory", None)
    )
    if server_mode:
        if factory is None:
            raise APIError(
                status_code=503,
                code="server_postgres_unavailable",
                message="Enterprise production profile requires PostgreSQL.",
            )
        try:
            conn = factory.connect()
        except Exception as exc:
            raise APIError(
                status_code=503,
                code="server_postgres_unavailable",
                message=f"Enterprise production profile database connection failed: {exc}",
            ) from exc
        raw_tenant = getattr(request.state, "tenant_id", None) or getattr(request.state, "workspace_id", "default")
        tenant_id = str(raw_tenant) if raw_tenant else "default"
        return conn, PostgresShopFloorRepository(conn, tenant_id)

    if factory is not None:
        try:
            conn = factory.connect()
            raw_tenant = getattr(request.state, "tenant_id", None) or getattr(request.state, "workspace_id", "default")
            tenant_id = str(raw_tenant) if raw_tenant else "default"
            return conn, PostgresShopFloorRepository(conn, tenant_id)
        except Exception:
            pass

    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return conn, SqliteShopFloorRepository(conn)


@router.post("/lots")
def register_lot(
    request: Request,
    payload: LotRegistrationRequest,
    user: ShopFloorManage,
) -> dict[str, Any]:
    """Register a new batch lot and link its consumed parent component lots."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        lot_record = LotTraceabilityRecord(
            workspace_id=workspace,
            lot_id=payload.lot_id,
            item_id=payload.item_id,
            batch_number=payload.batch_number,
            quantity_scaled=payload.quantity_scaled,
            scale_factor=payload.scale_factor,
            status=payload.status,
            notes=payload.notes,
        )
        parents = [(p.parent_lot_id, p.quantity_consumed_scaled) for p in payload.parent_lots]
        repo.register_lot(lot_record, parents)
        return {"status": "registered", "lot_id": lot_record.lot_id}
    except ShopFloorExecutionError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/lots/{lot_id}")
def get_lot(
    request: Request,
    lot_id: str,
    user: ShopFloorRead,
) -> dict[str, Any]:
    """Retrieve lot details and status."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        lot = repo.get_lot(workspace, lot_id)
        if not lot:
            raise APIError(status_code=404, code="lot_not_found", message=f"Lot {lot_id} not found")
        return {
            "lot_id": lot.lot_id,
            "item_id": lot.item_id,
            "batch_number": lot.batch_number,
            "quantity_scaled": lot.quantity_scaled,
            "scale_factor": lot.scale_factor,
            "status": lot.status,
            "notes": lot.notes,
        }
    finally:
        conn.close()


@router.post("/dispatch")
def dispatch_work_order(
    request: Request,
    payload: WorkOrderDispatchRequest,
    user: ShopFloorManage,
) -> dict[str, Any]:
    """Dispatch a work order to the shop floor with defined operation routing steps."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        domain_steps = tuple(
            ShopFloorOperationStep(
                step_id=s.step_id,
                work_order_id=s.work_order_id,
                operation_sequence=s.operation_sequence,
                work_center_id=s.work_center_id,
                operator_id=s.operator_id,
                status=s.status,
                actual_run_minutes=s.actual_run_minutes,
                quantity_completed_scaled=s.quantity_completed_scaled,
                quantity_scrapped_scaled=s.quantity_scrapped_scaled,
                scrap_reason_code=s.scrap_reason_code,
                started_at=s.started_at,
                completed_at=s.completed_at,
            )
            for s in payload.steps
        )
        dispatch = WorkOrderDispatch(
            workspace_id=workspace,
            dispatch_id=payload.dispatch_id,
            work_order_id=payload.work_order_id,
            item_id=payload.item_id,
            scheduled_quantity_scaled=payload.scheduled_quantity_scaled,
            dispatched_lot_id=payload.dispatched_lot_id,
            dispatched_at=payload.dispatched_at,
            steps=domain_steps,
        )
        repo.save_dispatch(dispatch)
        return {"status": "dispatched", "dispatch_id": dispatch.dispatch_id}
    except ShopFloorExecutionError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/dispatches/{dispatch_id}")
def get_dispatch(
    request: Request,
    dispatch_id: str,
    user: ShopFloorRead,
) -> dict[str, Any]:
    """Retrieve full dispatch and current progress across all routing steps."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        dispatch = repo.get_dispatch(workspace, dispatch_id)
        if not dispatch:
            raise APIError(status_code=404, code="dispatch_not_found", message=f"Dispatch {dispatch_id} not found")
        return {
            "dispatch_id": dispatch.dispatch_id,
            "work_order_id": dispatch.work_order_id,
            "item_id": dispatch.item_id,
            "scheduled_quantity_scaled": dispatch.scheduled_quantity_scaled,
            "dispatched_lot_id": dispatch.dispatched_lot_id,
            "dispatched_at": dispatch.dispatched_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "operation_sequence": s.operation_sequence,
                    "work_center_id": s.work_center_id,
                    "operator_id": s.operator_id,
                    "status": s.status,
                    "actual_run_minutes": s.actual_run_minutes,
                    "quantity_completed_scaled": s.quantity_completed_scaled,
                    "quantity_scrapped_scaled": s.quantity_scrapped_scaled,
                    "scrap_reason_code": s.scrap_reason_code,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                }
                for s in dispatch.steps
            ],
        }
    finally:
        conn.close()


@router.post("/steps/progress")
def progress_step(
    request: Request,
    payload: StepProgressRequest,
    user: ShopFloorManage,
) -> dict[str, Any]:
    """Progress an operation step with sequence validation and quantity conservation."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        dispatch = repo.get_dispatch(workspace, payload.dispatch_id)
        if not dispatch:
            raise APIError(status_code=404, code="dispatch_not_found", message=f"Dispatch {payload.dispatch_id} not found")

        s = payload.step
        domain_step = ShopFloorOperationStep(
            step_id=s.step_id,
            work_order_id=s.work_order_id,
            operation_sequence=s.operation_sequence,
            work_center_id=s.work_center_id,
            operator_id=s.operator_id,
            status=s.status,
            actual_run_minutes=s.actual_run_minutes,
            quantity_completed_scaled=s.quantity_completed_scaled,
            quantity_scrapped_scaled=s.quantity_scrapped_scaled,
            scrap_reason_code=s.scrap_reason_code,
            started_at=s.started_at,
            completed_at=s.completed_at,
        )
        validate_step_progression(dispatch, domain_step)
        repo.save_step(workspace, domain_step)
        return {"status": "step_updated", "step_id": domain_step.step_id, "step_status": domain_step.status}
    except ShopFloorExecutionError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


def _serialize_genealogy_node(node: Any) -> dict[str, Any]:
    return {
        "lot_id": node.lot_id,
        "item_id": node.item_id,
        "direction": node.direction,
        "children": [_serialize_genealogy_node(child) for child in node.children],
    }


@router.get("/genealogy/backward/{lot_id}")
def get_backward_genealogy(
    request: Request,
    lot_id: str,
    user: ShopFloorRead,
) -> dict[str, Any]:
    """Trace all raw materials and subcomponents consumed to manufacture this lot."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        edges = repo.get_genealogy_edges(workspace)
        item_map = repo.get_lot_item_map(workspace)
        tree = traverse_genealogy(lot_id, edges, item_map, direction="backward")
        return {"root_lot_id": lot_id, "genealogy": _serialize_genealogy_node(tree)}
    except ShopFloorExecutionError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/genealogy/forward/{lot_id}")
def get_forward_genealogy(
    request: Request,
    lot_id: str,
    user: ShopFloorRead,
) -> dict[str, Any]:
    """Trace all finished goods and parent assemblies that consumed this lot (recall analysis)."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        edges = repo.get_genealogy_edges(workspace)
        item_map = repo.get_lot_item_map(workspace)
        tree = traverse_genealogy(lot_id, edges, item_map, direction="forward")
        return {"root_lot_id": lot_id, "genealogy": _serialize_genealogy_node(tree)}
    except ShopFloorExecutionError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()
