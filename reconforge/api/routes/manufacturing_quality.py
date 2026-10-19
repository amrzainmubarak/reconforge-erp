"""FastAPI routes for Quality Inspection Plans, Non-Conformance Reports (NCR), and Rework Orders."""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.manufacturing_quality_rework import (
    NonConformanceReport,
    QualityInspectionPlan,
    QualityReworkError,
    QualitySpecification,
    ReworkOrder,
    ReworkRoutingStep,
)
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/manufacturing/quality", tags=["manufacturing-quality"])
require_quality_read = require_permission("manufacturing_execution.read")
require_quality_manage = require_permission("manufacturing_execution.manage")
Read = Annotated[LocalUser, Depends(require_quality_read)]
Manage = Annotated[LocalUser, Depends(require_quality_manage)]

SQLITE_QUALITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS quality_inspection_plans (
    plan_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    name TEXT NOT NULL,
    sample_size_units INTEGER NOT NULL,
    specifications_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, item_id, revision)
);

CREATE TABLE IF NOT EXISTS quality_ncrs (
    ncr_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    defect_code TEXT NOT NULL,
    defect_severity TEXT NOT NULL,
    inspector_id TEXT NOT NULL,
    quarantined_quantity_scaled INTEGER NOT NULL,
    status TEXT NOT NULL,
    disposition TEXT,
    disposition_notes TEXT,
    disposition_by TEXT,
    disposition_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_rework_orders (
    rework_order_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_work_order_id TEXT NOT NULL,
    ncr_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    rework_quantity_scaled INTEGER NOT NULL,
    rework_routing_steps_json TEXT NOT NULL,
    rework_cost_center TEXT NOT NULL,
    status TEXT NOT NULL,
    accumulated_rework_cost_minor INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""


def _get_db(request: Request) -> sqlite3.Connection:
    server_mode = bool(getattr(request.app.state, "server_mode", False))
    factory = (
        getattr(request.app.state, "postgres_finance_core_factory", None)
        or getattr(request.app.state, "postgres_identity_factory", None)
        or getattr(request.app.state, "postgres_connection_factory", None)
    )
    if server_mode and factory is None:
        raise APIError(
            status_code=503,
            code="server_postgres_unavailable",
            message="Enterprise production profile requires PostgreSQL.",
        )

    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    with conn:
        conn.executescript(SQLITE_QUALITY_SCHEMA)
    return conn


class QualitySpecPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    param_name: str = Field(min_length=1, max_length=64)
    target_value: int
    tolerance_lower: int
    tolerance_upper: int
    unit_of_measure: str = Field(default="scaled", min_length=1, max_length=16)
    is_critical: bool = True


class InspectionPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_id: str = Field(min_length=1, max_length=64)
    item_id: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    sample_size_units: int = Field(ge=1)
    specifications: list[QualitySpecPayload] = Field(min_length=1)


class EvaluateInspectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=64)
    measurements: dict[str, int]


class NCRCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ncr_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    work_order_id: str = Field(min_length=1, max_length=64)
    defect_code: str = Field(min_length=1, max_length=64)
    defect_severity: Literal["minor", "major", "critical"]
    inspector_id: str = Field(min_length=1, max_length=64)
    quarantined_quantity_scaled: int = Field(ge=1)


class NCRDispositionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    disposition: Literal["scrap", "rework", "return_to_vendor", "use_as_is"]
    notes: str = Field(min_length=1, max_length=255)


class ReworkStepPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step_number: int = Field(ge=1)
    work_center_id: str = Field(min_length=1, max_length=64)
    operation_description: str = Field(min_length=1, max_length=160)
    estimated_minutes: int = Field(ge=1)
    labor_rate_hourly_minor: int = Field(default=0, ge=0)


class ReworkCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rework_order_id: str = Field(min_length=1, max_length=64)
    parent_work_order_id: str = Field(min_length=1, max_length=64)
    ncr_id: str = Field(min_length=1, max_length=64)
    item_id: str = Field(min_length=1, max_length=64)
    rework_quantity_scaled: int = Field(ge=1)
    rework_routing_steps: list[ReworkStepPayload] = Field(min_length=1)
    rework_cost_center: str = Field(min_length=1, max_length=64)


class LogReworkStepPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step_number: int = Field(ge=1)
    actual_minutes: int = Field(ge=1)
    labor_rate_hourly_minor: int = Field(ge=1)


@router.post("/inspection-plans")
def register_inspection_plan(
    request: Request,
    payload: InspectionPlanPayload,
    user: Manage,
) -> dict[str, Any]:
    """Register quality inspection plan with parameter tolerances."""
    conn = _get_db(request)
    try:
        specs = tuple(
            QualitySpecification(
                param_name=s.param_name,
                target_value=s.target_value,
                tolerance_lower=s.tolerance_lower,
                tolerance_upper=s.tolerance_upper,
                unit_of_measure=s.unit_of_measure,
                is_critical=s.is_critical,
            )
            for s in payload.specifications
        )
        plan = QualityInspectionPlan(
            plan_id=payload.plan_id,
            item_id=payload.item_id,
            revision=payload.revision,
            name=payload.name,
            sample_size_units=payload.sample_size_units,
            specifications=specs,
        )
        workspace_id = getattr(request.state, "workspace_id", "default")
        specs_json = json.dumps([
            {
                "param_name": s.param_name,
                "target_value": s.target_value,
                "tolerance_lower": s.tolerance_lower,
                "tolerance_upper": s.tolerance_upper,
                "unit_of_measure": s.unit_of_measure,
                "is_critical": s.is_critical,
            }
            for s in plan.specifications
        ])
        with conn:
            conn.execute(
                """
                INSERT INTO quality_inspection_plans (
                    plan_id, workspace_id, item_id, revision, name,
                    sample_size_units, specifications_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT (workspace_id, item_id, revision) DO UPDATE SET
                    name = excluded.name,
                    sample_size_units = excluded.sample_size_units,
                    specifications_json = excluded.specifications_json
                """,
                (
                    plan.plan_id,
                    workspace_id,
                    plan.item_id,
                    plan.revision,
                    plan.name,
                    plan.sample_size_units,
                    specs_json,
                ),
            )
        return {
            "status": "registered",
            "plan_id": plan.plan_id,
            "item_id": plan.item_id,
            "revision": plan.revision,
            "specifications_count": len(plan.specifications),
        }
    except (QualityReworkError, PlatformError) as exc:
        raise APIError(status_code=422, code=getattr(exc, "code", "quality_plan_invalid"), message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/inspection-plans/{item_id}")
def get_inspection_plan(
    request: Request,
    item_id: str,
    user: Read,
    revision: str | None = Query(default=None),
) -> dict[str, Any]:
    """Retrieve quality inspection plan for item."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        if revision:
            cur = conn.execute(
                """
                SELECT plan_id, item_id, revision, name, sample_size_units, specifications_json
                FROM quality_inspection_plans
                WHERE workspace_id = ? AND item_id = ? AND revision = ?
                """,
                (workspace_id, item_id, revision),
            )
        else:
            cur = conn.execute(
                """
                SELECT plan_id, item_id, revision, name, sample_size_units, specifications_json
                FROM quality_inspection_plans
                WHERE workspace_id = ? AND item_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id, item_id),
            )
        row = cur.fetchone()
        if not row:
            raise APIError(status_code=404, code="plan_not_found", message=f"No inspection plan found for item '{item_id}'.")
        return {
            "plan_id": row[0],
            "item_id": row[1],
            "revision": row[2],
            "name": row[3],
            "sample_size_units": row[4],
            "specifications": json.loads(row[5]),
        }
    finally:
        conn.close()


@router.post("/evaluate")
def evaluate_lot_inspection(
    request: Request,
    payload: EvaluateInspectionPayload,
    user: Read,
) -> dict[str, Any]:
    """Evaluate measured lot inspection parameters against plan."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        cur = conn.execute(
            """
            SELECT specifications_json FROM quality_inspection_plans
            WHERE workspace_id = ? AND item_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (workspace_id, payload.item_id),
        )
        row = cur.fetchone()
        if not row:
            raise APIError(status_code=404, code="plan_not_found", message=f"No plan found for item '{payload.item_id}'.")
        specs_data = json.loads(row[0])
        specs = tuple(
            QualitySpecification(
                param_name=s["param_name"],
                target_value=s["target_value"],
                tolerance_lower=s["tolerance_lower"],
                tolerance_upper=s["tolerance_upper"],
                unit_of_measure=s.get("unit_of_measure", "scaled"),
                is_critical=s.get("is_critical", True),
            )
            for s in specs_data
        )
        plan = QualityInspectionPlan(
            plan_id="eval_plan",
            item_id=payload.item_id,
            revision="1.0",
            name="Evaluation Plan",
            sample_size_units=1,
            specifications=specs,
        )
        is_passed, defects = plan.evaluate_measurements(payload.measurements)
        return {
            "item_id": payload.item_id,
            "is_passed": is_passed,
            "status": "accepted" if is_passed else "rejected",
            "defects": defects,
        }
    finally:
        conn.close()


@router.post("/ncrs")
def create_ncr(
    request: Request,
    payload: NCRCreatePayload,
    user: Manage,
) -> dict[str, Any]:
    """Create a formal Non-Conformance Report (quarantining material)."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        ncr = NonConformanceReport(
            ncr_id=payload.ncr_id,
            lot_id=payload.lot_id,
            work_order_id=payload.work_order_id,
            defect_code=payload.defect_code,
            defect_severity=payload.defect_severity,
            inspector_id=payload.inspector_id,
            quarantined_quantity_scaled=payload.quarantined_quantity_scaled,
        )
        with conn:
            conn.execute(
                """
                INSERT INTO quality_ncrs (
                    ncr_id, workspace_id, lot_id, work_order_id,
                    defect_code, defect_severity, inspector_id,
                    quarantined_quantity_scaled, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', datetime('now'))
                """,
                (
                    ncr.ncr_id,
                    workspace_id,
                    ncr.lot_id,
                    ncr.work_order_id,
                    ncr.defect_code,
                    ncr.defect_severity,
                    ncr.inspector_id,
                    ncr.quarantined_quantity_scaled,
                ),
            )
        return {
            "status": "quarantined",
            "ncr_id": ncr.ncr_id,
            "lot_id": ncr.lot_id,
            "quarantined_quantity_scaled": ncr.quarantined_quantity_scaled,
        }
    finally:
        conn.close()


@router.post("/ncrs/{ncr_id}/disposition")
def disposition_ncr(
    request: Request,
    ncr_id: str,
    payload: NCRDispositionPayload,
    user: Manage,
) -> dict[str, Any]:
    """MRB disposition for a Non-Conformance Report."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        cur = conn.execute(
            """
            SELECT lot_id, work_order_id, defect_code, defect_severity,
                   inspector_id, quarantined_quantity_scaled, status
            FROM quality_ncrs
            WHERE workspace_id = ? AND ncr_id = ?
            """,
            (workspace_id, ncr_id),
        )
        row = cur.fetchone()
        if not row:
            raise APIError(status_code=404, code="ncr_not_found", message=f"NCR '{ncr_id}' not found.")
        ncr = NonConformanceReport(
            ncr_id=ncr_id,
            lot_id=row[0],
            work_order_id=row[1],
            defect_code=row[2],
            defect_severity=row[3],
            inspector_id=row[4],
            quarantined_quantity_scaled=row[5],
            status=row[6],
        )
        dispositioned = ncr.disposition_ncr(
            disposition=payload.disposition,
            notes=payload.notes,
            actor=user.username,
        )
        with conn:
            conn.execute(
                """
                UPDATE quality_ncrs
                SET status = ?, disposition = ?, disposition_notes = ?,
                    disposition_by = ?, disposition_at = datetime('now')
                WHERE workspace_id = ? AND ncr_id = ?
                """,
                (
                    dispositioned.status,
                    dispositioned.disposition,
                    dispositioned.disposition_notes,
                    dispositioned.disposition_by,
                    workspace_id,
                    ncr_id,
                ),
            )
        return {
            "status": dispositioned.status,
            "ncr_id": dispositioned.ncr_id,
            "disposition": dispositioned.disposition,
            "disposition_by": dispositioned.disposition_by,
        }
    except QualityReworkError as exc:
        raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.post("/rework-orders")
def create_rework_order(
    request: Request,
    payload: ReworkCreatePayload,
    user: Manage,
) -> dict[str, Any]:
    """Create a rework order for dispositioned NCR."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        steps = tuple(
            ReworkRoutingStep(
                step_number=s.step_number,
                work_center_id=s.work_center_id,
                operation_description=s.operation_description,
                estimated_minutes=s.estimated_minutes,
                labor_rate_hourly_minor=s.labor_rate_hourly_minor,
            )
            for s in payload.rework_routing_steps
        )
        rework = ReworkOrder(
            rework_order_id=payload.rework_order_id,
            parent_work_order_id=payload.parent_work_order_id,
            ncr_id=payload.ncr_id,
            item_id=payload.item_id,
            rework_quantity_scaled=payload.rework_quantity_scaled,
            rework_routing_steps=steps,
            rework_cost_center=payload.rework_cost_center,
        ).release()

        steps_json = json.dumps([
            {
                "step_number": s.step_number,
                "work_center_id": s.work_center_id,
                "operation_description": s.operation_description,
                "estimated_minutes": s.estimated_minutes,
                "actual_minutes": s.actual_minutes,
                "labor_rate_hourly_minor": s.labor_rate_hourly_minor,
            }
            for s in rework.rework_routing_steps
        ])
        with conn:
            conn.execute(
                """
                INSERT INTO quality_rework_orders (
                    rework_order_id, workspace_id, parent_work_order_id,
                    ncr_id, item_id, rework_quantity_scaled,
                    rework_routing_steps_json, rework_cost_center,
                    status, accumulated_rework_cost_minor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    rework.rework_order_id,
                    workspace_id,
                    rework.parent_work_order_id,
                    rework.ncr_id,
                    rework.item_id,
                    rework.rework_quantity_scaled,
                    steps_json,
                    rework.rework_cost_center,
                    rework.status,
                    rework.accumulated_rework_cost_minor,
                ),
            )
        return {
            "status": rework.status,
            "rework_order_id": rework.rework_order_id,
            "rework_quantity_scaled": rework.rework_quantity_scaled,
            "steps_count": len(rework.rework_routing_steps),
        }
    except QualityReworkError as exc:
        raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.post("/rework-orders/{rework_order_id}/log-step")
def log_rework_operation_step(
    request: Request,
    rework_order_id: str,
    payload: LogReworkStepPayload,
    user: Manage,
) -> dict[str, Any]:
    """Log actual rework operation step execution and accumulate labor costs."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        cur = conn.execute(
            """
            SELECT parent_work_order_id, ncr_id, item_id,
                   rework_quantity_scaled, rework_routing_steps_json,
                   rework_cost_center, status, accumulated_rework_cost_minor
            FROM quality_rework_orders
            WHERE workspace_id = ? AND rework_order_id = ?
            """,
            (workspace_id, rework_order_id),
        )
        row = cur.fetchone()
        if not row:
            raise APIError(status_code=404, code="rework_not_found", message=f"Rework order '{rework_order_id}' not found.")
        raw_steps = json.loads(row[4])
        steps = tuple(
            ReworkRoutingStep(
                step_number=s["step_number"],
                work_center_id=s["work_center_id"],
                operation_description=s["operation_description"],
                estimated_minutes=s["estimated_minutes"],
                actual_minutes=s.get("actual_minutes", 0),
                labor_rate_hourly_minor=s.get("labor_rate_hourly_minor", 0),
            )
            for s in raw_steps
        )
        rework = ReworkOrder(
            rework_order_id=rework_order_id,
            parent_work_order_id=row[0],
            ncr_id=row[1],
            item_id=row[2],
            rework_quantity_scaled=row[3],
            rework_routing_steps=steps,
            rework_cost_center=row[5],
            status=row[6],
            accumulated_rework_cost_minor=row[7],
        )
        updated = rework.log_rework_step(
            step_number=payload.step_number,
            actual_minutes=payload.actual_minutes,
            labor_rate_hourly_minor=payload.labor_rate_hourly_minor,
        )
        updated_steps_json = json.dumps([
            {
                "step_number": s.step_number,
                "work_center_id": s.work_center_id,
                "operation_description": s.operation_description,
                "estimated_minutes": s.estimated_minutes,
                "actual_minutes": s.actual_minutes,
                "labor_rate_hourly_minor": s.labor_rate_hourly_minor,
            }
            for s in updated.rework_routing_steps
        ])
        with conn:
            conn.execute(
                """
                UPDATE quality_rework_orders
                SET status = ?, rework_routing_steps_json = ?,
                    accumulated_rework_cost_minor = ?
                WHERE workspace_id = ? AND rework_order_id = ?
                """,
                (
                    updated.status,
                    updated_steps_json,
                    updated.accumulated_rework_cost_minor,
                    workspace_id,
                    rework_order_id,
                ),
            )
        return {
            "status": updated.status,
            "rework_order_id": updated.rework_order_id,
            "step_number": payload.step_number,
            "accumulated_rework_cost_minor": updated.accumulated_rework_cost_minor,
        }
    except QualityReworkError as exc:
        raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.post("/rework-orders/{rework_order_id}/complete")
def complete_rework_order(
    request: Request,
    rework_order_id: str,
    user: Manage,
) -> dict[str, Any]:
    """Complete a rework order after successful operations."""
    conn = _get_db(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        cur = conn.execute(
            """
            SELECT parent_work_order_id, ncr_id, item_id,
                   rework_quantity_scaled, rework_routing_steps_json,
                   rework_cost_center, status, accumulated_rework_cost_minor
            FROM quality_rework_orders
            WHERE workspace_id = ? AND rework_order_id = ?
            """,
            (workspace_id, rework_order_id),
        )
        row = cur.fetchone()
        if not row:
            raise APIError(status_code=404, code="rework_not_found", message=f"Rework order '{rework_order_id}' not found.")
        raw_steps = json.loads(row[4])
        steps = tuple(
            ReworkRoutingStep(
                step_number=s["step_number"],
                work_center_id=s["work_center_id"],
                operation_description=s["operation_description"],
                estimated_minutes=s["estimated_minutes"],
                actual_minutes=s.get("actual_minutes", 0),
                labor_rate_hourly_minor=s.get("labor_rate_hourly_minor", 0),
            )
            for s in raw_steps
        )
        rework = ReworkOrder(
            rework_order_id=rework_order_id,
            parent_work_order_id=row[0],
            ncr_id=row[1],
            item_id=row[2],
            rework_quantity_scaled=row[3],
            rework_routing_steps=steps,
            rework_cost_center=row[5],
            status=row[6],
            accumulated_rework_cost_minor=row[7],
        )
        completed = rework.complete(actor=user.username)
        with conn:
            conn.execute(
                """
                UPDATE quality_rework_orders
                SET status = 'completed', completed_at = datetime('now')
                WHERE workspace_id = ? AND rework_order_id = ?
                """,
                (workspace_id, rework_order_id),
            )
        return {
            "status": "completed",
            "rework_order_id": completed.rework_order_id,
            "total_rework_cost_minor": completed.accumulated_rework_cost_minor,
        }
    except QualityReworkError as exc:
        raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()
