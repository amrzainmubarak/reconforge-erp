"""Scoped foreign native AR, effective tax and historical functional posting."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.fixed_assets import project
from reconforge.api.routes.operational_finance import _authority
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.operational_fx_tax import ForeignInvoicePreparation, HistoricalRate, TaxComponent
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/operational-fx-tax", tags=["operational-fx-tax"])
Read = Annotated[LocalUser, Depends(require_permission("finance_core.read"))]
Manage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]
Review = Annotated[LocalUser, Depends(require_permission("finance_core.validate"))]
Post = Annotated[LocalUser, Depends(require_permission("finance_core.post"))]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RateRequest(StrictModel):
    rate: str = Field(pattern=r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?$")
    source: str = Field(min_length=1, max_length=200)
    effective_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class TaxRequest(StrictModel):
    policy_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=200)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    transaction_class: str = Field(min_length=1, max_length=160)
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    rate: str = Field(pattern=r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?$")
    account_code: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=200)


class InvoiceRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    invoice_number: str = Field(min_length=1, max_length=60)
    customer_code: str = Field(min_length=1, max_length=64)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    journal_code: str = Field(min_length=1, max_length=64)
    foreign_currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    net_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    original_rate: RateRequest
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    transaction_class: str = Field(min_length=1, max_length=160)
    taxes: list[TaxRequest] = Field(max_length=8)
    receivable_account_code: str = Field(min_length=1, max_length=64)
    revenue_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)
    gain_account_code: str = Field(min_length=1, max_length=64)
    loss_account_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class SettlementRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    foreign_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    settlement_rate: RateRequest
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


class PhaseRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def execute(request: Request, user: LocalUser,
            operation: Callable[[PostgresOperationalFxTaxRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="fx_backend_unavailable", message="Native foreign receivables require PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(operation(PostgresOperationalFxTaxRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = (403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409 if "conflict" in exc.code or "state_invalid" in exc.code else 400)
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="fx_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.post("/invoices")
def prepare_invoice(request: Request, payload: InvoiceRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(repository: PostgresOperationalFxTaxRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        args = payload.model_dump(exclude={"command_id", "net_minor", "original_rate", "taxes"})
        source = ForeignInvoicePreparation(**args, net_minor=int(payload.net_minor), original_rate=HistoricalRate(**payload.original_rate.model_dump()),
            taxes=tuple(TaxComponent(**tax.model_dump()) for tax in payload.taxes), workspace_id=scope.workspace_id,
            organization_id=str(scope.organization_id), legal_entity_id=str(scope.legal_entity_id), organization_code=scope.organization_code, entity_code=scope.entity_code)
        return {"plan": repository.prepare_invoice(source, command_id=payload.command_id, actor=actor)}

    return execute(request, user, run)


@router.get("/invoices")
def list_invoices(request: Request, user: Read, after: str = Query(default="", max_length=160), limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: repository.list_sources(
        {"workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id}, actor=actor, after=after, limit=limit))


@router.get("/invoices/{source_id}")
def get_invoice(request: Request, source_id: str, user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: {"invoice": repository.get(source_id, actor=actor)})


@router.post("/invoices/{source_id}/settlements")
def prepare_settlement(request: Request, source_id: str, payload: SettlementRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_settlement(source_id,
        **payload.model_dump(exclude={"foreign_minor", "settlement_rate"}), foreign_minor=int(payload.foreign_minor),
        settlement_rate=HistoricalRate(**payload.settlement_rate.model_dump()), actor=actor)})


@router.get("/plans/{plan_id}/evidence")
def get_evidence(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: {"evidence": repository.plan_evidence(plan_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    _authority(request, "finance_core.validate")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.review(plan_id, **payload.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    _authority(request, "finance_core.post")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.post(plan_id, **payload.model_dump(), actor=actor)})
