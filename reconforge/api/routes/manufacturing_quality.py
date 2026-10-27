"""Authenticated quality workflow records with explicit storage and effect boundaries."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.enterprise_scope import enterprise_transaction
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
from reconforge.infrastructure.postgres_manufacturing_quality import PostgresManufacturingQualityRepository
from reconforge.infrastructure.sqlite_manufacturing_quality import (
    SqliteManufacturingQualityRepository,
)

router = APIRouter(prefix="/manufacturing/quality", tags=["manufacturing-quality"])
require_quality_read = require_permission("manufacturing_execution.read")
require_quality_manage = require_permission("manufacturing_execution.manage")
Read = Annotated[LocalUser, Depends(require_quality_read)]
Manage = Annotated[LocalUser, Depends(require_quality_manage)]


@contextmanager
def _repository(
    request: Request, *, permissions: frozenset[str], require_hierarchy: bool = False,
) -> Iterator[tuple[SqliteManufacturingQualityRepository | PostgresManufacturingQualityRepository, str]]:
    try:
        with enterprise_transaction(
            request, permissions=permissions, require_hierarchy=require_hierarchy,
        ) as business:
            if business is not None:
                yield (
                    PostgresManufacturingQualityRepository(business.connection, business.scope.tenant_id),
                    business.scope.workspace_id,
                )
                return
            db_path = getattr(request.app.state, "db_path", None)
            if db_path is None:
                raise APIError(
                    status_code=500, code="db_not_configured", message="API database path is not configured."
                )
            connection = sqlite3.connect(db_path)
            connection.execute("PRAGMA foreign_keys=ON")
            try:
                repository = SqliteManufacturingQualityRepository(connection)
                if request.method.upper() == "POST":
                    connection.execute("BEGIN IMMEDIATE")
                with connection:
                    yield repository, getattr(request.state, "workspace_id", "default")
            finally:
                connection.close()
    except QualityReworkError as exc:
        forbidden = {"quality_actor_identity_denied", "quality_actor_authority_missing", "quality_self_disposition_denied"}
        status = 403 if exc.code in forbidden else 404 if exc.code == "quality_ncr_not_found" else 409 if exc.code == "quality_identifier_exists" else 422
        code = "ncr_not_found" if exc.code == "quality_ncr_not_found" else exc.code
        raise APIError(status_code=status, code=code, message=str(exc)) from exc


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
def register_inspection_plan(request: Request, payload: InspectionPlanPayload, user: Manage) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.manage"})) as (repo, workspace):
        plan = QualityInspectionPlan(
            plan_id=payload.plan_id,
            item_id=payload.item_id,
            revision=payload.revision,
            name=payload.name,
            sample_size_units=payload.sample_size_units,
            specifications=tuple(QualitySpecification(**spec.model_dump()) for spec in payload.specifications),
        )
        repo.save_plan(workspace, plan)
        return {
            "status": "registered",
            "plan_id": plan.plan_id,
            "item_id": plan.item_id,
            "revision": plan.revision,
            "specifications_count": len(plan.specifications),
        }


@router.get("/inspection-plans/{item_id}")
def get_inspection_plan(
    request: Request, item_id: str, user: Read, revision: str | None = Query(default=None)
) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.read"})) as (repo, workspace):
        plan = repo.get_plan(workspace, item_id, revision)
        if plan is None:
            raise APIError(status_code=404, code="plan_not_found", message="Inspection plan not found.")
        return asdict(plan)


@router.post("/evaluate")
def evaluate_lot_inspection(request: Request, payload: EvaluateInspectionPayload, user: Read) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.read"})) as (repo, workspace):
        plan = repo.get_plan(workspace, payload.item_id)
        if plan is None:
            raise APIError(status_code=404, code="plan_not_found", message="Inspection plan not found.")
        passed, defects = plan.evaluate_measurements(payload.measurements)
        return {
            "item_id": payload.item_id,
            "plan_id": plan.plan_id,
            "revision": plan.revision,
            "is_passed": passed,
            "status": "accepted" if passed else "rejected",
            "defects": defects,
        }


@router.post("/ncrs")
def create_ncr(request: Request, payload: NCRCreatePayload, user: Manage) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.manage"}), require_hierarchy=True) as (repo, workspace):
        if payload.inspector_id not in {user.id, user.username}:
            raise APIError(
                status_code=403,
                code="inspector_identity_denied",
                message="Inspector identity must be the authenticated actor.",
            )
        ncr = NonConformanceReport(
            ncr_id=payload.ncr_id,
            lot_id=payload.lot_id,
            work_order_id=payload.work_order_id,
            defect_code=payload.defect_code,
            defect_severity=payload.defect_severity,
            inspector_id=user.username,
            quarantined_quantity_scaled=payload.quarantined_quantity_scaled,
        )
        repo.create_ncr(workspace, ncr, creator_user_id=user.id, actor_label=user.username)
        # A requested hold in a quality record does not change native stock.
        return {
            "status": "recorded",
            "ncr_id": ncr.ncr_id,
            "lot_id": ncr.lot_id,
            "quarantined_quantity_scaled": ncr.quarantined_quantity_scaled,
            "inventory_effect": "not_posted",
            "inspector_user_id": user.id,
        }


@router.post("/ncrs/{ncr_id}/disposition")
def disposition_ncr(request: Request, ncr_id: str, payload: NCRDispositionPayload, user: Manage) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.manage"}), require_hierarchy=True) as (repo, workspace):
        updated = repo.disposition_ncr(
            workspace, ncr_id, disposition=payload.disposition, notes=payload.notes,
            actor_user_id=user.id, actor_label=user.username,
        )
        return {
            "status": updated.status,
            "ncr_id": updated.ncr_id,
            "disposition": updated.disposition,
            "disposition_by": updated.disposition_by,
            "disposition_by_user_id": user.id,
            "inventory_effect": "not_posted",
        }


@router.post("/rework-orders")
def create_rework_order(request: Request, payload: ReworkCreatePayload, user: Manage) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.manage"})) as (repo, workspace):
        ncr = repo.get_ncr(workspace, payload.ncr_id, for_update=True)
        if ncr is None:
            raise APIError(status_code=404, code="ncr_not_found", message="NCR not found.")
        if (
            ncr.status != "dispositioned"
            or ncr.disposition != "rework"
            or ncr.work_order_id != payload.parent_work_order_id
        ):
            raise APIError(
                status_code=409,
                code="rework_source_invalid",
                message="Rework requires its independently dispositioned source NCR.",
            )
        if (
            repo.ncr_rework_quantity(workspace, payload.ncr_id) + payload.rework_quantity_scaled
            > ncr.quarantined_quantity_scaled
        ):
            raise APIError(
                status_code=409,
                code="rework_quantity_exceeded",
                message="Rework quantity exceeds the recorded NCR allocation.",
            )
        rework = ReworkOrder(
            rework_order_id=payload.rework_order_id,
            parent_work_order_id=payload.parent_work_order_id,
            ncr_id=payload.ncr_id,
            item_id=payload.item_id,
            rework_quantity_scaled=payload.rework_quantity_scaled,
            rework_routing_steps=tuple(ReworkRoutingStep(**step.model_dump()) for step in payload.rework_routing_steps),
            rework_cost_center=payload.rework_cost_center,
        ).release()
        repo.create_rework(workspace, rework)
        return {
            "status": rework.status,
            "rework_order_id": rework.rework_order_id,
            "rework_quantity_scaled": rework.rework_quantity_scaled,
            "steps_count": len(rework.rework_routing_steps),
            "financial_effect": "not_posted",
        }


@router.post("/rework-orders/{rework_order_id}/log-step")
def log_rework_operation_step(
    request: Request, rework_order_id: str, payload: LogReworkStepPayload, user: Manage
) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.manage"})) as (repo, workspace):
        rework = repo.get_rework(workspace, rework_order_id, for_update=True)
        if rework is None:
            raise APIError(status_code=404, code="rework_not_found", message="Rework order not found.")
        updated = rework.log_rework_step(**payload.model_dump())
        repo.update_rework(workspace, updated)
        return {
            "status": updated.status,
            "rework_order_id": updated.rework_order_id,
            "step_number": payload.step_number,
            "accumulated_rework_cost_minor": updated.accumulated_rework_cost_minor,
            "financial_effect": "not_posted",
        }


@router.post("/rework-orders/{rework_order_id}/complete")
def complete_rework_order(request: Request, rework_order_id: str, user: Manage) -> dict[str, Any]:
    with _repository(request, permissions=frozenset({"manufacturing_execution.manage"})) as (repo, workspace):
        rework = repo.get_rework(workspace, rework_order_id, for_update=True)
        if rework is None:
            raise APIError(status_code=404, code="rework_not_found", message="Rework order not found.")
        if any(step.actual_minutes <= 0 for step in rework.rework_routing_steps):
            raise APIError(
                status_code=409,
                code="rework_operations_incomplete",
                message="Every routing operation requires an execution record.",
            )
        completed = rework.complete(actor=user.username)
        repo.update_rework(workspace, completed)
        return {
            "status": "completed",
            "rework_order_id": completed.rework_order_id,
            "total_rework_cost_minor": completed.accumulated_rework_cost_minor,
            "financial_effect": "not_posted",
        }
