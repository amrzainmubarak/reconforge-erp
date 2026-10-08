"""Selected-scope stock sales with real reservations, FIFO, GL and receivables."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    get_auth_db,
    get_current_user,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_finance_core import execute_postgres_finance_core_scoped, server_finance_core_enabled
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.stock_sales import StockSalesApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_stock_sales import OPERATION_PERMISSIONS, READ, PostgresStockSalesRepository
from reconforge.platform.common import current_server_principal

router = APIRouter(prefix="/stock-sales", tags=["stock-sales"])


def _required(permissions: frozenset[str] | set[str]) -> Callable[..., LocalUser]:
    def dependency(request: Request, user: LocalUser = Depends(get_current_user),
                   connection: sqlite3.Connection | None = Depends(get_auth_db)) -> LocalUser:
        for permission in sorted(permissions):
            require_permission(permission)(request, user, connection)
        return user
    cast(Any, dependency).__reconforge_permissions__ = frozenset(permissions)
    cast(Any, dependency).__reconforge_permission_mode__ = "all"
    return dependency


Reader = Annotated[LocalUser, Depends(_required(READ))]
Creator = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["create"]))]
Submitter = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["submit"]))]
Approver = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["approve"]))]
Reserver = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["reserve"]))]
IssueMaker = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["prepare-issue"]))]
IssueReviewer = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["review-issue"]))]
Deliverer = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["deliver"]))]
InvoiceMaker = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["prepare-invoice"]))]
InvoiceReviewer = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["review-invoice"]))]
InvoicePoster = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["invoice"]))]
CollectionMaker = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["prepare-collection"]))]
CollectionReviewer = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["review-collection"]))]
Collector = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["collect"]))]
Canceller = Annotated[LocalUser, Depends(_required(OPERATION_PERMISSIONS["cancel"]))]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=100)


class OrderRequest(Command):
    number: str = Field(min_length=1, max_length=64)
    customer_code: str = Field(min_length=1, max_length=64)
    customer_reference: str = Field(min_length=1, max_length=160)
    item_code: str = Field(min_length=1, max_length=64)
    warehouse_code: str = Field(min_length=1, max_length=64)
    location_code: str = Field(min_length=1, max_length=64)
    quantity: str = Field(min_length=1, max_length=64)
    unit_price_minor: str = Field(pattern="^[1-9][0-9]{0,18}$")
    currency_code: str = Field(pattern="^[A-Z]{3}$")
    order_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str = Field(min_length=1, max_length=500)
    discount_basis_points: int = Field(default=0, ge=0, lt=10000)


class TransitionRequest(Command):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class IssueRequest(TransitionRequest):
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    policy_code: str = Field(min_length=1, max_length=64)


class InvoiceRequest(TransitionRequest):
    invoice_number: str = Field(min_length=1, max_length=64)
    invoice_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    receivable_account_code: str = Field(min_length=1, max_length=64)
    revenue_account_code: str = Field(min_length=1, max_length=64)


class CollectionRequest(TransitionRequest):
    receipt_number: str = Field(min_length=1, max_length=64)
    receipt_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    cash_account_code: str = Field(min_length=1, max_length=64)


def _execute(request: Request, user: LocalUser, operation: str,
             invoke: Callable[[StockSalesApplicationService, PostingActor], dict[str, Any]]) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="stock_sales_backend_unavailable", message="Product sales requires the configured PostgreSQL profile.")
    principal = current_server_principal()
    if principal is None or principal.user.id != user.id:
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    scope = request_execution_scope(request)
    for permission in sorted(OPERATION_PERMISSIONS.get(operation, READ)):
        enforce_server_scoped_permission(request, permission=permission, tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id, organization_id=scope.organization_id, entity_id=scope.legal_entity_id)
    actor = PostingActor(user.id, user.username, principal.permissions, principal.principal_type, principal.step_up_active)

    def callback(repository: Any, selected: Any) -> dict[str, Any]:
        if not selected.organization_id or not selected.legal_entity_id or not selected.organization_code or not selected.entity_code:
            raise APIError(status_code=403, code="stock_sales_scope_denied", message="Select an organization and legal entity.")
        adapter = PostgresStockSalesRepository(repository.connection, selected.tenant_id, workspace_id=selected.workspace_id,
            organization_id=selected.organization_id, legal_entity_id=selected.legal_entity_id,
            organization_code=selected.organization_code, entity_code=selected.entity_code)
        try:
            return invoke(StockSalesApplicationService(adapter), actor)
        except FinancePostingError as exc:
            denied = any(word in exc.code for word in ("denied", "permission", "human", "step_up"))
            raise APIError(status_code=403 if denied else 409, code=exc.code, message=str(exc)) from exc

    return cast(dict[str, Any], execute_postgres_finance_core_scoped(request, callback))


def _transition(request: Request, user: LocalUser, identifier: str, operation: str, body: TransitionRequest) -> dict[str, Any]:
    payload = body.model_dump()
    command, version, reason = payload.pop("command_id"), payload.pop("expected_version"), payload.pop("reason")
    return _execute(request, user, operation, lambda service, actor: service.act(identifier, operation,
        expected_version=version, command_id=command, reason=reason, parameters=payload, actor=actor))


@router.get("/options")
def options(request: Request, user: Reader) -> dict[str, Any]:
    return _execute(request, user, "read", lambda service, actor: service.options(actor=actor))


@router.get("/orders")
def orders(request: Request, user: Reader) -> dict[str, Any]:
    return _execute(request, user, "read", lambda service, actor: service.list(actor=actor))


@router.get("/orders/{identifier}")
def order(identifier: str, request: Request, user: Reader) -> dict[str, Any]:
    return _execute(request, user, "read", lambda service, actor: service.get(identifier, actor=actor))


@router.post("/orders", status_code=201)
def create(request: Request, body: OrderRequest, user: Creator) -> dict[str, Any]:
    payload = body.model_dump()
    command = payload.pop("command_id")
    payload["unit_price_minor"] = int(payload["unit_price_minor"])
    return _execute(request, user, "create", lambda service, actor: service.create(StockOrder(**payload), command_id=command, actor=actor))


@router.post("/orders/{identifier}/submit")
def submit(identifier: str, request: Request, body: TransitionRequest, user: Submitter) -> dict[str, Any]:
    return _transition(request, user, identifier, "submit", body)


@router.post("/orders/{identifier}/approve")
def approve(identifier: str, request: Request, body: TransitionRequest, user: Approver) -> dict[str, Any]:
    return _transition(request, user, identifier, "approve", body)


@router.post("/orders/{identifier}/reserve")
def reserve(identifier: str, request: Request, body: TransitionRequest, user: Reserver) -> dict[str, Any]:
    return _transition(request, user, identifier, "reserve", body)


@router.post("/orders/{identifier}/issue/prepare")
def prepare_issue(identifier: str, request: Request, body: IssueRequest, user: IssueMaker) -> dict[str, Any]:
    return _transition(request, user, identifier, "prepare-issue", body)


@router.post("/orders/{identifier}/issue/review")
def review_issue(identifier: str, request: Request, body: TransitionRequest, user: IssueReviewer) -> dict[str, Any]:
    return _transition(request, user, identifier, "review-issue", body)


@router.post("/orders/{identifier}/deliver")
def deliver(identifier: str, request: Request, body: TransitionRequest, user: Deliverer) -> dict[str, Any]:
    return _transition(request, user, identifier, "deliver", body)


@router.post("/orders/{identifier}/invoice/prepare")
def prepare_invoice(identifier: str, request: Request, body: InvoiceRequest, user: InvoiceMaker) -> dict[str, Any]:
    return _transition(request, user, identifier, "prepare-invoice", body)


@router.post("/orders/{identifier}/invoice/review")
def review_invoice(identifier: str, request: Request, body: TransitionRequest, user: InvoiceReviewer) -> dict[str, Any]:
    return _transition(request, user, identifier, "review-invoice", body)


@router.post("/orders/{identifier}/invoice/post")
def invoice(identifier: str, request: Request, body: TransitionRequest, user: InvoicePoster) -> dict[str, Any]:
    return _transition(request, user, identifier, "invoice", body)


@router.post("/orders/{identifier}/collection/prepare")
def prepare_collection(identifier: str, request: Request, body: CollectionRequest, user: CollectionMaker) -> dict[str, Any]:
    return _transition(request, user, identifier, "prepare-collection", body)


@router.post("/orders/{identifier}/collection/review")
def review_collection(identifier: str, request: Request, body: TransitionRequest, user: CollectionReviewer) -> dict[str, Any]:
    return _transition(request, user, identifier, "review-collection", body)


@router.post("/orders/{identifier}/collection/post")
def collect(identifier: str, request: Request, body: TransitionRequest, user: Collector) -> dict[str, Any]:
    return _transition(request, user, identifier, "collect", body)


@router.post("/orders/{identifier}/cancel")
def cancel(identifier: str, request: Request, body: TransitionRequest, user: Canceller) -> dict[str, Any]:
    return _transition(request, user, identifier, "cancel", body)
