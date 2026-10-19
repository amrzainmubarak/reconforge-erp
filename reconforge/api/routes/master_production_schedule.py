"""FastAPI routes for Master Production Scheduling (MPS), ATP, and shortage procurement."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.master_production_schedule import (
    MPSBucketDemand,
    MPSError,
    compute_master_production_schedule,
)
from reconforge.infrastructure.postgres_mps import PostgresMPSRepository
from reconforge.infrastructure.sqlite_mps import SQLiteMPSRepository

router = APIRouter(prefix="/manufacturing/mps", tags=["manufacturing-mps"])

MPSRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"manufacturing_supply_plan.read", "manufacturing_supply_plan.manage"})),
]
MPSManage = Annotated[LocalUser, Depends(require_permission("manufacturing_supply_plan.manage"))]


class MPSBucketDemandInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    bucket_index: int = Field(ge=0, le=104)
    bucket_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    bucket_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sales_orders_scaled: int = Field(ge=0)
    forecast_demand_scaled: int = Field(ge=0)
    scheduled_receipts_scaled: int = Field(ge=0)

    def to_domain(self) -> MPSBucketDemand:
        return MPSBucketDemand(
            bucket_index=self.bucket_index,
            bucket_start_date=self.bucket_start_date,
            bucket_end_date=self.bucket_end_date,
            sales_orders_scaled=self.sales_orders_scaled,
            forecast_demand_scaled=self.forecast_demand_scaled,
            scheduled_receipts_scaled=self.scheduled_receipts_scaled,
        )


class ComputeMPSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    plan_id: str = Field(min_length=1, max_length=64)
    plan_name: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=32)
    item_id: str = Field(min_length=1, max_length=64)
    unit_of_measure: str = Field(default="EA", min_length=1, max_length=16)
    quantity_scale: int = Field(default=1000, ge=1, le=1_000_000)
    safety_stock_scaled: int = Field(ge=0)
    lot_size_multiple_scaled: int = Field(default=1000, gt=0)
    opening_inventory_scaled: int = Field(ge=0)
    buckets: list[MPSBucketDemandInput] = Field(min_length=1, max_length=104)
    preferred_supplier_id: str = Field(default="SUP_DEFAULT", min_length=1, max_length=64)
    unit_price_ceiling_minor: int = Field(default=10_000, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


def _get_repository(request: Request) -> tuple[Any, SQLiteMPSRepository | PostgresMPSRepository]:
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
        return conn, PostgresMPSRepository(conn, tenant_id)

    if factory is not None:
        try:
            conn = factory.connect()
            raw_tenant = getattr(request.state, "tenant_id", None) or getattr(request.state, "workspace_id", "default")
            tenant_id = str(raw_tenant) if raw_tenant else "default"
            return conn, PostgresMPSRepository(conn, tenant_id)
        except Exception:
            pass

    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return conn, SQLiteMPSRepository(conn)


@router.post("/compute")
def compute_and_save_mps(
    request: Request,
    payload: ComputeMPSRequest,
    user: MPSManage,
) -> dict[str, Any]:
    """Compute deterministic MPS schedule, ATP, and generate shortage purchase requisitions."""
    conn, repo = _get_repository(request)
    try:
        domain_buckets = [b.to_domain() for b in payload.buckets]

        plan_result = compute_master_production_schedule(
            plan_id=payload.plan_id,
            plan_name=payload.plan_name,
            revision=payload.revision,
            item_id=payload.item_id,
            unit_of_measure=payload.unit_of_measure,
            quantity_scale=payload.quantity_scale,
            safety_stock_scaled=payload.safety_stock_scaled,
            lot_size_multiple_scaled=payload.lot_size_multiple_scaled,
            opening_inventory_scaled=payload.opening_inventory_scaled,
            buckets=domain_buckets,
            preferred_supplier_id=payload.preferred_supplier_id,
            unit_price_ceiling_minor=payload.unit_price_ceiling_minor,
            currency=payload.currency,
        )

        workspace_id = getattr(request.state, "workspace_id", "default")
        record_id = repo.save_plan(
            workspace_id=workspace_id,
            plan_result=plan_result,
            created_by=user.username,
        )

        return {
            "status": "computed",
            "record_id": record_id,
            "plan_digest": plan_result.plan_digest,
            "plan_id": plan_result.plan_id,
            "revision": plan_result.revision,
            "schedule_rows_count": len(plan_result.schedule_rows),
            "sourcing_requisitions_count": len(plan_result.sourcing_requisitions),
            "plan": asdict(plan_result),
        }
    except MPSError as exc:
        raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/plans")
def list_mps_plans(
    request: Request,
    user: MPSRead,
    item_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """List MPS plans in the workspace."""
    conn, repo = _get_repository(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        plans = repo.list_plans(workspace_id=workspace_id, item_id=item_id)
        return {"total_count": len(plans), "plans": plans}
    finally:
        conn.close()


@router.get("/plans/{plan_id}/{revision}")
def get_mps_plan(
    request: Request,
    plan_id: str,
    revision: str,
    user: MPSRead,
) -> dict[str, Any]:
    """Retrieve an exact MPS plan with schedule rows and ATP."""
    conn, repo = _get_repository(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        plan = repo.get_plan(workspace_id=workspace_id, plan_id=plan_id, revision=revision)
        if not plan:
            raise APIError(status_code=404, code="mps_plan_not_found", message=f"MPS plan {plan_id} r{revision} not found.")
        return plan
    finally:
        conn.close()


@router.get("/requisitions")
def list_sourcing_requisitions(
    request: Request,
    user: MPSRead,
    plan_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """List generated shortage sourcing requisitions."""
    conn, repo = _get_repository(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        reqs = repo.list_requisitions(workspace_id=workspace_id, plan_id=plan_id)
        return {"total_count": len(reqs), "requisitions": reqs}
    finally:
        conn.close()
