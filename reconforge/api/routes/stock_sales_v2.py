"""Server-fixed net-exclusive Stock v2 over the native monetary source owner."""

from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator

from reconforge.api.errors import APIError
from reconforge.api.monetary_public_contract import MAX_MINOR, MonetaryResponseError
from reconforge.api.monetary_stock_contract import (
    project_monetary_stock_options,
    project_monetary_stock_response,
)
from reconforge.api.monetary_valuation_contract import project_monetary_valuation
from reconforge.api.routes import stock_sales as legacy
from reconforge.api.routes.operational_fx_tax import (
    PhaseRequest,
    RateRequest,
    TaxRequest,
)
from reconforge.api.routes.operational_fx_tax import (
    RevaluationRequest as FxRevaluationRequest,
)
from reconforge.api.routes.operational_fx_tax import (
    RevaluationReversalRequest as FxRevaluationReversalRequest,
)
from reconforge.api.server_finance_core import execute_postgres_finance_core_scoped, server_finance_core_enabled
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.stock_sales import StockSalesApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_monetary_stock_sales import (
    OPERATION_PERMISSIONS,
    READ,
    VALUATION_PERMISSIONS,
    PostgresMonetaryStockSalesRepository,
)
from reconforge.platform.common import current_server_principal

router = APIRouter(prefix="/stock-sales", tags=["stock-sales-monetary"])
CollectionMaker = Annotated[LocalUser, Depends(legacy._required(OPERATION_PERMISSIONS["prepare-collection"]))]
CollectionReviewer = Annotated[LocalUser, Depends(legacy._required(OPERATION_PERMISSIONS["review-collection"]))]
ValuationMaker = Annotated[LocalUser, Depends(legacy._required(VALUATION_PERMISSIONS["prepare"]))]
ValuationInverseMaker = Annotated[LocalUser, Depends(legacy._required(VALUATION_PERMISSIONS["prepare_reversal"]))]
ValuationReviewer = Annotated[LocalUser, Depends(legacy._required(VALUATION_PERMISSIONS["review"]))]
ValuationPoster = Annotated[LocalUser, Depends(legacy._required(VALUATION_PERMISSIONS["post"]))]


class ValuationRequest(FxRevaluationRequest):
    @field_validator("posting_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("An exact ISO business date is required.")
        return value


class ValuationReversalRequest(FxRevaluationReversalRequest):
    @field_validator("posting_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("An exact ISO business date is required.")
        return value


class OrderRequest(legacy.OrderRequest):
    @field_validator("unit_price_minor")
    @classmethod
    def bounded_price(cls, value: str) -> str:
        if int(value) > MAX_MINOR:
            raise ValueError("The unit price exceeds the bounded native contract.")
        return value

    @field_validator("order_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("An exact ISO business date is required.")
        return value


class InvoiceRequest(legacy.InvoiceRequest):
    invoice_number: str = Field(min_length=1, max_length=60)
    cash_account_code: str = Field(min_length=1, max_length=64)
    refund_liability_account_code: str = Field(min_length=1, max_length=64)
    gain_account_code: str = Field(min_length=1, max_length=64)
    loss_account_code: str = Field(min_length=1, max_length=64)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    transaction_class: str = Field(min_length=1, max_length=160)
    taxes: list[TaxRequest] = Field(max_length=8)
    original_rate: RateRequest | None

    @field_validator("invoice_date", "due_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("An exact ISO business date is required.")
        return value


class CollectionRequest(legacy.TransitionRequest):
    receipt_number: str = Field(min_length=1, max_length=60)
    receipt_date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    settlement_rate: RateRequest | None

    @field_validator("amount_minor")
    @classmethod
    def bounded_amount(cls, value: str) -> str:
        if int(value) > MAX_MINOR:
            raise ValueError("The collection exceeds the bounded native contract.")
        return value

    @field_validator("receipt_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("An exact ISO business date is required.")
        return value


def _execute_owner(request: Request, user: LocalUser, permissions: frozenset[str] | set[str],
                   invoke: Callable[[PostgresMonetaryStockSalesRepository, PostingActor], dict[str, Any]],
                   project: Callable[[Any, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="stock_monetary_backend_unavailable", message="Monetary product sales require PostgreSQL.")
    principal = current_server_principal()
    if principal is None or principal.user.id != user.id:
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    scope = request_execution_scope(request)
    for permission in sorted(permissions):
        legacy.enforce_server_scoped_permission(request, permission=permission, tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id, organization_id=scope.organization_id, entity_id=scope.legal_entity_id)
    actor = PostingActor(user.id, user.username, principal.permissions, principal.principal_type, principal.step_up_active)

    def callback(finance: Any, selected: Any) -> dict[str, Any]:
        if not selected.organization_id or not selected.legal_entity_id or not selected.organization_code or not selected.entity_code:
            raise APIError(status_code=403, code="stock_monetary_scope_denied", message="Select an organization and legal entity.")
        try:
            owner = PostgresMonetaryStockSalesRepository(finance.connection, selected.tenant_id, workspace_id=selected.workspace_id,
                organization_id=selected.organization_id, legal_entity_id=selected.legal_entity_id,
                organization_code=selected.organization_code, entity_code=selected.entity_code)
            result = invoke(owner, actor)
            return project(result, {
                "workspace_id": selected.workspace_id, "organization_id": selected.organization_id, "legal_entity_id": selected.legal_entity_id,
            })
        except MonetaryResponseError as exc:
            raise APIError(status_code=503, code="stock_monetary_response_invalid", message="The native monetary acknowledgement could not be verified.") from exc
        except FinancePostingError as exc:
            denied = any(word in exc.code for word in ("denied", "permission", "human", "step_up"))
            raise APIError(status_code=403 if denied else 404 if "not_found" in exc.code else 409, code=exc.code, message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, callback)


def execute(request: Request, user: LocalUser, operation: str,
            invoke: Callable[[StockSalesApplicationService, PostingActor], dict[str, Any]]) -> dict[str, Any]:
    return _execute_owner(request, user, OPERATION_PERMISSIONS.get(operation, READ),
        lambda owner, actor: invoke(StockSalesApplicationService(owner), actor),
        lambda result, scope: project_monetary_stock_options(result) if operation == "options" else project_monetary_stock_response(result, scope, listing=operation == "list"))


def execute_valuation(request: Request, user: LocalUser, identifier: str, operation: str,
                      invoke: Callable[[PostgresMonetaryStockSalesRepository, PostingActor], dict[str, Any]],
                      plan_id: str | None = None) -> dict[str, Any]:
    return _execute_owner(request, user, VALUATION_PERMISSIONS[operation], invoke,
        lambda result, scope: {"plan": project_monetary_valuation(result, scope, identifier, plan_id)})


def _transition(request: Request, user: LocalUser, identifier: str, operation: str, body: legacy.TransitionRequest) -> dict[str, Any]:
    fields = body.model_dump()
    command, version, reason = fields.pop("command_id"), fields.pop("expected_version"), fields.pop("reason")
    if operation == "prepare-collection":
        fields["amount_minor"] = int(fields["amount_minor"])
    return execute(request, user, operation, lambda service, actor: service.act(identifier, operation,
        expected_version=version, command_id=command, reason=reason, parameters=fields, actor=actor))


@router.get("/options")
def options(request: Request, user: legacy.Reader) -> dict[str, Any]:
    return execute(request, user, "options", lambda service, actor: service.options(actor=actor))


@router.get("/orders")
def orders(request: Request, user: legacy.Reader) -> dict[str, Any]:
    return execute(request, user, "list", lambda service, actor: service.list(actor=actor))


@router.get("/orders/{identifier}")
def order(identifier: str, request: Request, user: legacy.Reader) -> dict[str, Any]:
    return execute(request, user, "read", lambda service, actor: service.get(identifier, actor=actor))


@router.post("/orders", status_code=201)
def create(request: Request, body: OrderRequest, user: legacy.Creator) -> dict[str, Any]:
    fields = body.model_dump()
    command = fields.pop("command_id")
    fields["unit_price_minor"] = int(fields["unit_price_minor"])
    return execute(request, user, "create", lambda service, actor: service.create(StockOrder(**fields), command_id=command, actor=actor))


@router.post("/orders/{identifier}/submit")
def submit(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.Submitter) -> dict[str, Any]:
    return _transition(request, user, identifier, "submit", body)


@router.post("/orders/{identifier}/approve")
def approve(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.Approver) -> dict[str, Any]:
    return _transition(request, user, identifier, "approve", body)


@router.post("/orders/{identifier}/reserve")
def reserve(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.Reserver) -> dict[str, Any]:
    return _transition(request, user, identifier, "reserve", body)


@router.post("/orders/{identifier}/issue/prepare")
def prepare_issue(identifier: str, request: Request, body: legacy.IssueRequest, user: legacy.IssueMaker) -> dict[str, Any]:
    return _transition(request, user, identifier, "prepare-issue", body)


@router.post("/orders/{identifier}/issue/review")
def review_issue(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.IssueReviewer) -> dict[str, Any]:
    return _transition(request, user, identifier, "review-issue", body)


@router.post("/orders/{identifier}/deliver")
def deliver(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.Deliverer) -> dict[str, Any]:
    return _transition(request, user, identifier, "deliver", body)


@router.post("/orders/{identifier}/invoice/prepare")
def prepare_invoice(identifier: str, request: Request, body: InvoiceRequest, user: legacy.InvoiceMaker) -> dict[str, Any]:
    return _transition(request, user, identifier, "prepare-invoice", body)


@router.post("/orders/{identifier}/invoice/review")
def review_invoice(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.InvoiceReviewer) -> dict[str, Any]:
    return _transition(request, user, identifier, "review-invoice", body)


@router.post("/orders/{identifier}/invoice/post")
def invoice(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.InvoicePoster) -> dict[str, Any]:
    return _transition(request, user, identifier, "invoice", body)


@router.post("/orders/{identifier}/collection/prepare")
def prepare_collection(identifier: str, request: Request, body: CollectionRequest, user: CollectionMaker) -> dict[str, Any]:
    return _transition(request, user, identifier, "prepare-collection", body)


@router.post("/orders/{identifier}/collection/review")
def review_collection(identifier: str, request: Request, body: legacy.TransitionRequest, user: CollectionReviewer) -> dict[str, Any]:
    return _transition(request, user, identifier, "review-collection", body)


@router.post("/orders/{identifier}/collection/post")
def collect(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.Collector) -> dict[str, Any]:
    return _transition(request, user, identifier, "collect", body)


@router.post("/orders/{identifier}/cancel")
def cancel(identifier: str, request: Request, body: legacy.TransitionRequest, user: legacy.Canceller) -> dict[str, Any]:
    return _transition(request, user, identifier, "cancel", body)


@router.post("/orders/{identifier}/valuations")
def prepare_valuation(identifier: str, request: Request, body: ValuationRequest, user: ValuationMaker) -> dict[str, Any]:
    fields = body.model_dump(exclude={"closing_rate"})
    return execute_valuation(request, user, identifier, "prepare", lambda owner, actor: owner.prepare_valuation(identifier,
        **fields, closing_rate=HistoricalRate(**body.closing_rate.model_dump()), actor=actor))


@router.post("/orders/{identifier}/valuation-reversals")
def prepare_valuation_reversal(identifier: str, request: Request, body: ValuationReversalRequest, user: ValuationInverseMaker) -> dict[str, Any]:
    return execute_valuation(request, user, identifier, "prepare_reversal", lambda owner, actor: owner.prepare_valuation_reversal(identifier, **body.model_dump(), actor=actor))


@router.get("/orders/{identifier}/fx-plans/{plan_id}")
def get_valuation(identifier: str, plan_id: str, request: Request, user: legacy.Reader) -> dict[str, Any]:
    return execute_valuation(request, user, identifier, "read", lambda owner, actor: owner.get_valuation(identifier, plan_id, actor=actor), plan_id)


@router.post("/orders/{identifier}/fx-plans/{plan_id}/review")
def review_valuation(identifier: str, plan_id: str, request: Request, body: PhaseRequest, user: ValuationReviewer) -> dict[str, Any]:
    return execute_valuation(request, user, identifier, "review", lambda owner, actor: owner.review_valuation(identifier, plan_id, **body.model_dump(), actor=actor), plan_id)


@router.post("/orders/{identifier}/fx-plans/{plan_id}/post")
def post_valuation(identifier: str, plan_id: str, request: Request, body: PhaseRequest, user: ValuationPoster) -> dict[str, Any]:
    return execute_valuation(request, user, identifier, "post", lambda owner, actor: owner.post_valuation(identifier, plan_id, **body.model_dump(), actor=actor), plan_id)
