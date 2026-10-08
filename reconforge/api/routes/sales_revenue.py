"""Real selected-entity service sales, native receivables and balanced GL."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request
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
from reconforge.application.sales_revenue import SalesRevenueApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.sales_revenue import SalesInvoicePreparation, SalesLine, SalesQuotation
from reconforge.infrastructure.postgres_sales_revenue import PostgresSalesRevenueRepository
from reconforge.platform.common import current_server_principal

router = APIRouter(prefix="/sales-revenue", tags=["sales-revenue"])
READ = frozenset({"sales.read", "receivables.read", "finance_core.read"})
MANAGE = READ | frozenset({"sales.manage"})
INVOICE_PREPARE = MANAGE | frozenset({"receivables.manage", "finance_core.manage"})
INVOICE_REVIEW = READ | frozenset({"sales.approve", "receivables.approve", "finance_core.validate"})
INVOICE_POST = MANAGE | frozenset({"receivables.approve", "finance_core.post"})
COLLECTION_PREPARE = MANAGE | frozenset({"finance_core.manage"})
COLLECTION_REVIEW = READ | frozenset({"sales.approve", "finance_core.validate"})
COLLECTION_POST = MANAGE | frozenset({"receivables.manage", "finance_core.post"})


def _required(permissions: frozenset[str]) -> Callable[..., LocalUser]:
    def dependency(
        request: Request,
        user: LocalUser = Depends(get_current_user),
        connection: sqlite3.Connection | None = Depends(get_auth_db),
    ) -> LocalUser:
        for permission in sorted(permissions):
            require_permission(permission)(request, user, connection)
        return user

    cast(Any, dependency).__reconforge_permissions__ = permissions
    cast(Any, dependency).__reconforge_permission_mode__ = "all"
    return dependency


Reader = Annotated[LocalUser, Depends(_required(READ))]
Manager = Annotated[LocalUser, Depends(_required(MANAGE))]
Approver = Annotated[LocalUser, Depends(_required(READ | frozenset({"sales.approve"})))]
InvoiceMaker = Annotated[LocalUser, Depends(_required(INVOICE_PREPARE))]
InvoiceReviewer = Annotated[LocalUser, Depends(_required(INVOICE_REVIEW))]
InvoicePoster = Annotated[LocalUser, Depends(_required(INVOICE_POST))]
CollectionMaker = Annotated[LocalUser, Depends(_required(COLLECTION_PREPARE))]
CollectionReviewer = Annotated[LocalUser, Depends(_required(COLLECTION_REVIEW))]
CollectionPoster = Annotated[LocalUser, Depends(_required(COLLECTION_POST))]


class ClosedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=100)


class LineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str = Field(min_length=1, max_length=500)
    quantity: str = Field(min_length=1, max_length=64)
    unit_price_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    discount_basis_points: int = Field(default=0, ge=0, lt=10000)


class QuotationRequest(ClosedRequest):
    number: str = Field(min_length=1, max_length=64)
    customer_code: str = Field(min_length=1, max_length=64)
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_until: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency_code: str = Field(pattern="^[A-Z]{3}$")
    lines: list[LineRequest] = Field(min_length=1, max_length=16)


class VersionRequest(ClosedRequest):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class FulfillmentRequest(VersionRequest):
    reference: str = Field(min_length=1, max_length=160)
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class InvoiceRequest(VersionRequest):
    invoice_number: str = Field(min_length=1, max_length=64)
    invoice_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    receivable_account_code: str = Field(min_length=1, max_length=64)
    revenue_account_code: str = Field(min_length=1, max_length=64)


class CollectionRequest(VersionRequest):
    receipt_number: str = Field(min_length=1, max_length=64)
    receipt_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    cash_account_code: str = Field(min_length=1, max_length=64)


def _execute(
    request: Request,
    user: LocalUser,
    operation: Callable[[SalesRevenueApplicationService, PostingActor], dict[str, Any]],
) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(
            status_code=503,
            code="sales_backend_unavailable",
            message="Service sales requires the configured PostgreSQL profile.",
        )
    principal = current_server_principal()
    if principal is None or principal.user.id != user.id:
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    scope = request_execution_scope(request)
    required = (
        READ
        if request.method == "GET"
        else (
            INVOICE_PREPARE
            if request.url.path.endswith("/invoice/prepare")
            else INVOICE_REVIEW
            if request.url.path.endswith("/invoice/review")
            else INVOICE_POST
            if request.url.path.endswith("/invoice/post")
            else COLLECTION_PREPARE
            if request.url.path.endswith("/collection/prepare")
            else COLLECTION_REVIEW
            if request.url.path.endswith("/collection/review")
            else COLLECTION_POST
            if request.url.path.endswith("/collection/post")
            else READ | frozenset({"sales.approve"})
            if request.url.path.endswith("/approve")
            else MANAGE
        )
    )
    for permission in sorted(required):
        enforce_server_scoped_permission(
            request,
            permission=permission,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
        )
    actor = PostingActor(
        user.id, user.username, principal.permissions, principal.principal_type, principal.step_up_active
    )

    def invoke(repository: Any, scope: Any) -> dict[str, Any]:
        if (
            not scope.organization_id
            or not scope.legal_entity_id
            or not scope.organization_code
            or not scope.entity_code
        ):
            raise APIError(
                status_code=403, code="sales_scope_denied", message="Select a canonical organization and legal entity."
            )
        try:
            sales = PostgresSalesRevenueRepository(
                repository.connection,
                scope.tenant_id,
                workspace_id=scope.workspace_id,
                organization_id=scope.organization_id,
                legal_entity_id=scope.legal_entity_id,
                organization_code=scope.organization_code,
                entity_code=scope.entity_code,
            )
            return operation(SalesRevenueApplicationService(sales), actor)
        except FinancePostingError as exc:
            status = (
                403
                if any(word in exc.code for word in ("denied", "required"))
                else 409
                if "conflict" in exc.code
                else 400
            )
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except ValueError as exc:
            raise APIError(
                status_code=400, code="sales_request_invalid", message="Sales dates or exact values are invalid."
            ) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/documents")
def documents(request: Request, user: Reader, after: Annotated[str, Query(max_length=160)] = "") -> dict[str, Any]:
    return _execute(request, user, lambda sales, actor: sales.list(actor=actor, after=after))


@router.get("/options")
def options(request: Request, user: Reader) -> dict[str, Any]:
    return _execute(request, user, lambda sales, actor: sales.options(actor=actor))


@router.get("/documents/{identifier}")
def document(request: Request, identifier: str, user: Reader) -> dict[str, Any]:
    return _execute(request, user, lambda sales, actor: {"document": sales.get(identifier, actor=actor)})


@router.post("/quotations")
def create(request: Request, payload: QuotationRequest, user: Manager) -> dict[str, Any]:
    quotation = SalesQuotation(
        number=payload.number,
        customer_code=payload.customer_code,
        business_date=payload.business_date,
        valid_until=payload.valid_until,
        currency_code=payload.currency_code,
        lines=tuple(
            SalesLine(
                description=line.description,
                quantity=line.quantity,
                unit_price_minor=int(line.unit_price_minor),
                discount_basis_points=line.discount_basis_points,
            )
            for line in payload.lines
        ),
    )
    return _execute(
        request,
        user,
        lambda sales, actor: {"document": sales.create(quotation, command_id=payload.command_id, actor=actor)},
    )


def _transition(
    request: Request, identifier: str, payload: VersionRequest, user: LocalUser, operation: str
) -> dict[str, Any]:
    return _execute(
        request,
        user,
        lambda sales, actor: {
            "document": sales.transition(identifier, operation=operation, actor=actor, **payload.model_dump())
        },
    )


@router.post("/documents/{identifier}/submit")
def submit(request: Request, identifier: str, payload: VersionRequest, user: Manager) -> dict[str, Any]:
    return _transition(request, identifier, payload, user, "submit")


@router.post("/documents/{identifier}/approve")
def approve(request: Request, identifier: str, payload: VersionRequest, user: Approver) -> dict[str, Any]:
    return _transition(request, identifier, payload, user, "approve")


@router.post("/documents/{identifier}/order")
def order(request: Request, identifier: str, payload: FulfillmentRequest, user: Manager) -> dict[str, Any]:
    return _transition(request, identifier, payload, user, "order")


@router.post("/documents/{identifier}/fulfill")
def fulfill(request: Request, identifier: str, payload: FulfillmentRequest, user: Manager) -> dict[str, Any]:
    return _transition(request, identifier, payload, user, "fulfill")


@router.post("/documents/{identifier}/cancel")
def cancel(request: Request, identifier: str, payload: VersionRequest, user: Manager) -> dict[str, Any]:
    return _transition(request, identifier, payload, user, "cancel")


@router.post("/documents/{identifier}/invoice/prepare")
def prepare_invoice(request: Request, identifier: str, payload: InvoiceRequest, user: InvoiceMaker) -> dict[str, Any]:
    preparation = SalesInvoicePreparation(**payload.model_dump(exclude={"command_id", "expected_version"}))
    return _execute(
        request,
        user,
        lambda sales, actor: {
            "document": sales.prepare_invoice(
                identifier,
                preparation,
                expected_version=payload.expected_version,
                command_id=payload.command_id,
                actor=actor,
            )
        },
    )


@router.post("/documents/{identifier}/invoice/review")
def review_invoice(request: Request, identifier: str, payload: VersionRequest, user: InvoiceReviewer) -> dict[str, Any]:
    return _execute(
        request,
        user,
        lambda sales, actor: {"document": sales.review_invoice(identifier, actor=actor, **payload.model_dump())},
    )


@router.post("/documents/{identifier}/invoice/post")
def post_invoice(request: Request, identifier: str, payload: VersionRequest, user: InvoicePoster) -> dict[str, Any]:
    return _execute(
        request,
        user,
        lambda sales, actor: {"document": sales.post_invoice(identifier, actor=actor, **payload.model_dump())},
    )


@router.post("/documents/{identifier}/collection/prepare")
def prepare_collection(
    request: Request, identifier: str, payload: CollectionRequest, user: CollectionMaker
) -> dict[str, Any]:
    return _execute(
        request,
        user,
        lambda sales, actor: {"document": sales.prepare_collection(identifier, actor=actor, **payload.model_dump())},
    )


@router.post("/documents/{identifier}/collection/review")
def review_collection(
    request: Request, identifier: str, payload: VersionRequest, user: CollectionReviewer
) -> dict[str, Any]:
    return _execute(
        request,
        user,
        lambda sales, actor: {"document": sales.review_collection(identifier, actor=actor, **payload.model_dump())},
    )


@router.post("/documents/{identifier}/collection/post")
def post_collection(
    request: Request, identifier: str, payload: VersionRequest, user: CollectionPoster
) -> dict[str, Any]:
    return _execute(
        request,
        user,
        lambda sales, actor: {"document": sales.post_collection(identifier, actor=actor, **payload.model_dump())},
    )
