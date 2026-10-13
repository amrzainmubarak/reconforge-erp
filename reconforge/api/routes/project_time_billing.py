"""Approved whole project time published through existing native AR and GL."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.operational_finance import _authority
from reconforge.api.routes.people_project_payroll import people_scope, project
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.application.project_time_billing import ProjectTimeBillingService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.people_project_payroll import minor_text
from reconforge.domain.project_time_billing import ProjectPriceAgreement
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository

router = APIRouter(prefix="/project-time-billing", tags=["project-time-billing"])
PERMISSIONS = {
    "read": frozenset({"project_time_billing.read"}),
    "evidence": frozenset({"project_time_billing.read", "finance_core.read", "people_project_payroll.read", "receivables.read"}),
    "manage": frozenset({"project_time_billing.manage", "receivables.read"}),
    "approve_price": frozenset({"project_time_billing.approve_price"}),
    "prepare": frozenset({"project_time_billing.prepare", "finance_core.manage", "receivables.manage", "people_project_payroll.read"}),
    "collect": frozenset({"project_time_billing.collect", "finance_core.manage", "receivables.receive"}),
    "review": frozenset({"project_time_billing.review", "finance_core.validate", "receivables.manage"}),
    "post": frozenset({"project_time_billing.post", "finance_core.post", "receivables.approve", "receivables.receive"}),
}
Read = Annotated[LocalUser, Depends(required(PERMISSIONS["read"]))]
Evidence = Annotated[LocalUser, Depends(required(PERMISSIONS["evidence"]))]
Manage = Annotated[LocalUser, Depends(required(PERMISSIONS["manage"]))]
ApprovePrice = Annotated[LocalUser, Depends(required(PERMISSIONS["approve_price"]))]
Prepare = Annotated[LocalUser, Depends(required(PERMISSIONS["prepare"]))]
Collect = Annotated[LocalUser, Depends(required(PERMISSIONS["collect"]))]
Review = Annotated[LocalUser, Depends(required(PERMISSIONS["review"]))]
Post = Annotated[LocalUser, Depends(required(PERMISSIONS["post"]))]
Minor = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)


class PriceRequest(Command):
    customer_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    project_id: str = Field(min_length=1, max_length=160)
    valid_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_through: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    hourly_price_minor: Minor
    reason: str = Field(min_length=1, max_length=500)


class PriceApproval(Command):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class InvoiceRequest(Command):
    time_ids: list[str] = Field(min_length=1, max_length=1000)
    price_ids: list[str] = Field(min_length=1, max_length=999)
    customer_code: str = Field(min_length=1, max_length=64)
    invoice_number: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    receivable_account_code: str = Field(min_length=1, max_length=64)
    revenue_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)


class CollectionRequest(Command):
    amount_minor: Minor
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class PhaseRequest(Command):
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def execute(request: Request, user: LocalUser, permission: str,
            operation: Callable[[PostgresProjectTimeBillingRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    _authority(request, "project_time_billing." + permission)
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="project_billing_backend_unavailable", message="Source-owned project billing requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(operation(PostgresProjectTimeBillingRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
    return execute_postgres_finance_core_scoped(request, invoke)


@router.post("/prices")
def register_price(request: Request, payload: PriceRequest, user: Manage) -> Any:
    return execute(request, user, "manage", lambda repo, actor, scope: {"price": repo.register_price(
        ProjectPriceAgreement(people_scope(scope), payload.customer_code, payload.project_id, payload.valid_from, payload.valid_through,
            payload.currency_code, minor_text(payload.hourly_price_minor, positive=True), payload.reason), command_id=payload.command_id, actor=actor)})


@router.post("/prices/{price_id}/approve")
def approve_price(price_id: str, request: Request, payload: PriceApproval, user: ApprovePrice) -> Any:
    return execute(request, user, "approve_price", lambda repo, actor, _: {"price": repo.approve_price(
        price_id, expected_digest=payload.expected_digest, command_id=payload.command_id, actor=actor)})


@router.post("/invoices")
def prepare_invoice(request: Request, payload: InvoiceRequest, user: Prepare) -> Any:
    return execute(request, user, "prepare", lambda repo, actor, scope: {"plan": repo.prepare_invoice(
        people_scope(scope), **payload.model_dump(exclude={"command_id"}), command_id=payload.command_id, actor=actor)})


@router.post("/invoices/{invoice_id}/collections")
def prepare_collection(invoice_id: str, request: Request, payload: CollectionRequest, user: Collect) -> Any:
    return execute(request, user, "collect", lambda repo, actor, _: {"plan": repo.prepare_collection(invoice_id,
        amount_minor=minor_text(payload.amount_minor, positive=True), period_id=payload.period_id,
        posting_date=payload.posting_date, command_id=payload.command_id, actor=actor)})


def phase(action: Literal["review", "post", "cancel"], plan_id: str, request: Request, payload: PhaseRequest, user: LocalUser) -> Any:
    return execute(request, user, "prepare" if action == "cancel" else action, lambda repo, actor, _: {"plan":
        ProjectTimeBillingService(repo).financial_phase(action, plan_id, expected_plan_digest=payload.expected_plan_digest,
            command_id=payload.command_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(plan_id: str, request: Request, payload: PhaseRequest, user: Review) -> Any:
    return phase("review", plan_id, request, payload, user)


@router.post("/plans/{plan_id}/post")
def post(plan_id: str, request: Request, payload: PhaseRequest, user: Post) -> Any:
    return phase("post", plan_id, request, payload, user)


@router.post("/plans/{plan_id}/cancel")
def cancel(plan_id: str, request: Request, payload: PhaseRequest, user: Prepare) -> Any:
    return phase("cancel", plan_id, request, payload, user)


@router.get("/plans/{plan_id}")
def get(plan_id: str, request: Request, user: Evidence) -> Any:
    return execute(request, user, "read", lambda repo, actor, _: {"plan": repo.get(plan_id, actor=actor)})


@router.get("/invoices/{invoice_id}/evidence")
def evidence(invoice_id: str, request: Request, user: Evidence) -> Any:
    return execute(request, user, "read", lambda repo, actor, _: {"evidence": repo.evidence(invoice_id, actor=actor)})


@router.get("/catalog")
def catalog(request: Request, user: Evidence, after: str = Query(default="", max_length=160), limit: int = Query(default=25, ge=1, le=100)) -> Any:
    return execute(request, user, "read", lambda repo, actor, scope: repo.catalog(people_scope(scope), after=after, limit=limit, actor=actor))
