"""FastAPI routes for Project WBS, Rate Cards, Milestone Billing, and Financial Posture."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.models import utc_now_text
from reconforge.domain.project_milestone_billing import (
    ProjectBillingError,
    ProjectMilestone,
    ProjectWBSTask,
    ResourceRateCard,
    TaskStatus,
    generate_milestone_invoice,
    verify_milestone_completion,
)
from reconforge.infrastructure.postgres_project_milestone_billing import (
    PostgresProjectMilestoneBillingRepository,
)
from reconforge.infrastructure.sqlite_project_billing import SqliteProjectBillingRepository

router = APIRouter(prefix="/projects/billing", tags=["project-billing"])

ProjectRead = Annotated[LocalUser, Depends(require_any_permission({"project_time_billing.read", "project_time_billing.manage"}))]
ProjectManage = Annotated[LocalUser, Depends(require_permission("project_time_billing.manage"))]


class WBSTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    task_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    parent_task_id: str | None = None
    planned_hours: int = Field(default=0, ge=0)
    budget_cost_minor: int = Field(default=0, ge=0)
    currency: str = Field(min_length=3, max_length=6)
    status: TaskStatus = "planned"


class RateCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rate_card_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    resource_role: str = Field(min_length=1, max_length=128)
    hourly_cost_rate_minor: int = Field(ge=0)
    hourly_bill_rate_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=6)


class MilestoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    milestone_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    contract_line_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    milestone_amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=6)
    due_date: str = Field(min_length=1)


class VerifyMilestoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verified_at: str = Field(default_factory=utc_now_text)


class BillMilestoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    customer_code: str = Field(min_length=1, max_length=128)
    invoice_id: str = Field(min_length=1, max_length=128)
    issued_at: str = Field(default_factory=utc_now_text)


class TimeLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    log_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    resource_role: str = Field(min_length=1, max_length=128)
    hours_worked: int = Field(gt=0)
    log_date: str = Field(min_length=1)


def _get_repo(request: Request) -> tuple[Any, SqliteProjectBillingRepository | PostgresProjectMilestoneBillingRepository]:
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
        return conn, PostgresProjectMilestoneBillingRepository(conn, tenant_id)

    if factory is not None:
        try:
            conn = factory.connect()
            raw_tenant = getattr(request.state, "tenant_id", None) or getattr(request.state, "workspace_id", "default")
            tenant_id = str(raw_tenant) if raw_tenant else "default"
            return conn, PostgresProjectMilestoneBillingRepository(conn, tenant_id)
        except Exception:
            pass

    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return conn, SqliteProjectBillingRepository(conn)


@router.post("/tasks")
def create_wbs_task(
    request: Request,
    payload: WBSTaskRequest,
    user: ProjectManage,
) -> dict[str, Any]:
    """Create or update a Work Breakdown Structure task."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        task = ProjectWBSTask(
            workspace_id=workspace,
            task_id=payload.task_id,
            project_id=payload.project_id,
            task_code=payload.task_code,
            name=payload.name,
            parent_task_id=payload.parent_task_id,
            planned_hours=payload.planned_hours,
            budget_cost_minor=payload.budget_cost_minor,
            currency=payload.currency,
            status=payload.status,
        )
        repo.save_task(task)
        return {"status": "saved", "task_id": task.task_id}
    except ProjectBillingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/tasks/{project_id}")
def list_tasks(
    request: Request,
    project_id: str,
    user: ProjectRead,
) -> dict[str, Any]:
    """List all WBS tasks for a given project."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        tasks = repo.list_tasks(workspace, project_id)
        return {
            "project_id": project_id,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "task_code": t.task_code,
                    "name": t.name,
                    "parent_task_id": t.parent_task_id,
                    "planned_hours": t.planned_hours,
                    "budget_cost_minor": t.budget_cost_minor,
                    "currency": t.currency,
                    "status": t.status,
                }
                for t in tasks
            ],
        }
    finally:
        conn.close()


@router.post("/rate-cards")
def create_rate_card(
    request: Request,
    payload: RateCardRequest,
    user: ProjectManage,
) -> dict[str, Any]:
    """Define role rate cards for project time and material billing."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        card = ResourceRateCard(
            workspace_id=workspace,
            rate_card_id=payload.rate_card_id,
            project_id=payload.project_id,
            resource_role=payload.resource_role,
            hourly_cost_rate_minor=payload.hourly_cost_rate_minor,
            hourly_bill_rate_minor=payload.hourly_bill_rate_minor,
            currency=payload.currency,
        )
        repo.save_rate_card(card)
        return {"status": "saved", "rate_card_id": card.rate_card_id}
    except ProjectBillingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.post("/milestones")
def create_milestone(
    request: Request,
    payload: MilestoneRequest,
    user: ProjectManage,
) -> dict[str, Any]:
    """Create a project milestone linked to a customer contract line item."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        milestone = ProjectMilestone(
            workspace_id=workspace,
            milestone_id=payload.milestone_id,
            project_id=payload.project_id,
            contract_line_id=payload.contract_line_id,
            title=payload.title,
            milestone_amount_minor=payload.milestone_amount_minor,
            currency=payload.currency,
            due_date=payload.due_date,
        )
        repo.save_milestone(milestone)
        return {"status": "saved", "milestone_id": milestone.milestone_id}
    except ProjectBillingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/milestones/{milestone_id}")
def get_milestone(
    request: Request,
    milestone_id: str,
    user: ProjectRead,
) -> dict[str, Any]:
    """Retrieve milestone status and details."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        m = repo.get_milestone(workspace, milestone_id)
        if not m:
            raise APIError(status_code=404, code="milestone_not_found", message=f"Milestone {milestone_id} not found")
        return {
            "milestone_id": m.milestone_id,
            "project_id": m.project_id,
            "contract_line_id": m.contract_line_id,
            "title": m.title,
            "milestone_amount_minor": m.milestone_amount_minor,
            "currency": m.currency,
            "due_date": m.due_date,
            "status": m.status,
            "verified_by": m.verified_by,
            "verified_at": m.verified_at,
        }
    finally:
        conn.close()


@router.post("/milestones/{milestone_id}/verify")
def verify_milestone(
    request: Request,
    milestone_id: str,
    payload: VerifyMilestoneRequest,
    user: ProjectManage,
) -> dict[str, Any]:
    """Verify deliverable completion for a milestone."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        m = repo.get_milestone(workspace, milestone_id)
        if not m:
            raise APIError(status_code=404, code="milestone_not_found", message=f"Milestone {milestone_id} not found")
        verified = verify_milestone_completion(m, user.username, payload.verified_at)
        repo.save_milestone(verified)
        return {"status": "verified", "milestone_id": verified.milestone_id, "verified_by": verified.verified_by}
    except ProjectBillingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.post("/milestones/{milestone_id}/bill")
def bill_milestone(
    request: Request,
    milestone_id: str,
    payload: BillMilestoneRequest,
    user: ProjectManage,
) -> dict[str, Any]:
    """Bill a verified milestone and generate accounts receivable invoice."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        m = repo.get_milestone(workspace, milestone_id)
        if not m:
            raise APIError(status_code=404, code="milestone_not_found", message=f"Milestone {milestone_id} not found")
        updated_m, invoice = generate_milestone_invoice(
            m,
            customer_code=payload.customer_code,
            invoice_id=payload.invoice_id,
            issued_at=payload.issued_at,
        )
        repo.save_milestone_invoice(updated_m, invoice)
        return {
            "status": "billed",
            "invoice_id": invoice.invoice_id,
            "milestone_id": invoice.milestone_id,
            "customer_code": invoice.customer_code,
            "billed_amount_minor": invoice.billed_amount_minor,
            "currency": invoice.currency,
        }
    except ProjectBillingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.post("/time-logs")
def log_project_time(
    request: Request,
    payload: TimeLogRequest,
    user: ProjectManage,
) -> dict[str, Any]:
    """Log billable hours against a project task with automated rate card valuation."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        cost, billable = repo.log_time(
            workspace_id=workspace,
            log_id=payload.log_id,
            project_id=payload.project_id,
            task_id=payload.task_id,
            role=payload.resource_role,
            hours=payload.hours_worked,
            date=payload.log_date,
        )
        return {
            "log_id": payload.log_id,
            "actual_cost_minor": cost,
            "billable_amount_minor": billable,
        }
    except ProjectBillingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/summary/{project_id}")
def get_project_financial_summary(
    request: Request,
    project_id: str,
    user: ProjectRead,
    currency: str = Query(default="USD"),
) -> dict[str, Any]:
    """Retrieve full project financial posture: budget, actual cost, billed revenue, and WIP."""
    conn, repo = _get_repo(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        posture = repo.get_financial_posture(workspace, project_id, currency)
        return {
            "project_id": posture.project_id,
            "currency": posture.currency,
            "budget_cost_minor": posture.budget_cost_minor,
            "actual_cost_minor": posture.actual_cost_minor,
            "total_billed_minor": posture.total_billed_minor,
            "unbilled_wip_minor": posture.unbilled_wip_minor,
            "profit_margin_bps": posture.profit_margin_bps,
        }
    finally:
        conn.close()
