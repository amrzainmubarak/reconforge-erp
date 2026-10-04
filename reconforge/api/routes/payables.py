"""Authenticated Accounts Payable and three-way matching routes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    enforce_server_scoped_permissions,
    get_local_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.api.server_payables import (
    PayablesExecutionScope,
    PayablesObject,
    execute_postgres_payables,
    server_payables_enabled,
)
from reconforge.auth.field_access import (
    project_payables_payment_link,
    project_payables_payment_link_reversal,
    project_payables_purchase_order,
    project_payables_receipt,
    project_payables_supplier,
    project_payables_supplier_invoice,
    project_payables_three_way_match,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_payables_payment_link import PostgresPayablesPaymentLinkRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.payables import PayablesService, PurchaseOrderLineInput, SupplierInvoiceLineInput
from reconforge.platform.payables_payment_link import PayablesPaymentLinkService

router = APIRouter(prefix="/payables", tags=["payables"])
PageLimit = Annotated[int, Query(ge=1, le=1_000)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
PayablesRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"payables.read", "payables.manage", "payables.match", "payables.approve", "payables.settle", "payables.reverse"})),
]
PayablesManage = Annotated[LocalUser, Depends(require_permission("payables.manage"))]
PayablesMatch = Annotated[LocalUser, Depends(require_permission("payables.match"))]
PayablesApprove = Annotated[LocalUser, Depends(require_permission("payables.approve"))]
PayablesSettle = Annotated[LocalUser, Depends(require_permission("payables.settle"))]
PayablesReverse = Annotated[LocalUser, Depends(require_permission("payables.reverse"))]
T = TypeVar("T")


class SupplierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    currency_code: str = Field(min_length=3, max_length=3)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    entity_code: str = Field(default="", max_length=64)
    tax_identifier: str = Field(default="", max_length=160)
    status: str = Field(default="Active", max_length=32)


class PurchaseOrderLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str = Field(min_length=1, max_length=64)
    ordered_quantity: str = Field(min_length=1, max_length=64)
    unit_price_minor: int = Field(ge=0)
    description: str = Field(default="", max_length=500)
    tax_minor: int = Field(default=0, ge=0)


class PurchaseOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_number: str = Field(min_length=1, max_length=64)
    supplier_code: str = Field(min_length=1, max_length=64)
    order_date: str = Field(min_length=10, max_length=10)
    currency_code: str = Field(min_length=3, max_length=3)
    lines: list[PurchaseOrderLineRequest] = Field(min_length=1, max_length=1_000)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    entity_code: str = Field(default="", max_length=64)
    branch_code: str = Field(default="", max_length=64)
    expected_date: str = Field(default="", max_length=10)
    idempotency_key: str = Field(default="", max_length=200)


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class PaymentLinkRequest(BaseModel):
    """The immutable reference to one already-posted AP/cash settlement effect."""

    model_config = ConfigDict(extra="forbid")

    finance_effect_id: str = Field(min_length=1, max_length=160)
    ap_account_id: str = Field(min_length=1, max_length=160)
    cash_account_id: str = Field(min_length=1, max_length=160)
    expected_invoice_version: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=160)


class PaymentLinkReversalRequest(BaseModel):
    """The exact posted Finance inverse accepted to unwind one AP allocation."""

    model_config = ConfigDict(extra="forbid")

    reversal_finance_effect_id: str = Field(min_length=1, max_length=160)
    expected_invoice_version: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=160)


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_number: str = Field(min_length=1, max_length=64)
    purchase_order_id: str = Field(min_length=1, max_length=160)
    receipt_date: str = Field(min_length=10, max_length=10)
    quantities: dict[str, str] = Field(min_length=1, max_length=1_000)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    idempotency_key: str = Field(default="", max_length=200)


class SupplierInvoiceLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_line_id: str = Field(min_length=1, max_length=160)
    invoiced_quantity: str = Field(min_length=1, max_length=64)
    unit_price_minor: int = Field(ge=0)
    line_total_minor: int = Field(ge=0)
    description: str = Field(default="", max_length=500)
    tax_minor: int = Field(default=0, ge=0)


class SupplierInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_number: str = Field(min_length=1, max_length=100)
    supplier_code: str = Field(min_length=1, max_length=64)
    invoice_date: str = Field(min_length=10, max_length=10)
    currency_code: str = Field(min_length=3, max_length=3)
    total_minor: int = Field(ge=0)
    lines: list[SupplierInvoiceLineRequest] = Field(min_length=1, max_length=1_000)
    purchase_order_id: str = Field(default="", max_length=160)
    tax_minor: int = Field(default=0, ge=0)
    due_date: str = Field(default="", max_length=10)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    entity_code: str = Field(default="", max_length=64)
    idempotency_key: str = Field(default="", max_length=200)


def _error(code: str, exc: Exception, *, status_code: int = 400) -> APIError:
    return APIError(status_code=status_code, code=code, message=str(exc))


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local Payables database is not configured for this request.")
    return connection


def _server_scope(request: Request, permissions: frozenset[str], *, amount: Decimal | None = None) -> RequestExecutionScope:
    scope = request_execution_scope(request)
    if len(permissions) == 1:
        enforce_server_scoped_permission(
            request,
            permission=next(iter(permissions)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
            amount=amount,
        )
    else:
        enforce_server_scoped_permissions(
            request,
            permissions=permissions,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
            amount=amount,
        )
    return scope


def _server_call(
    request: Request,
    permissions: frozenset[str],
    operation: Callable[[PostgresPayablesRepository, PayablesExecutionScope], T],
    *,
    amount: Decimal | None = None,
    organization_code: str = "",
    entity_code: str = "",
    object_refs: tuple[tuple[PayablesObject, str], ...] = (),
    supplier_code: str = "",
) -> T:
    _server_scope(request, permissions, amount=amount)
    return execute_postgres_payables(
        request,
        operation,
        organization_code=organization_code,
        entity_code=entity_code,
        object_refs=object_refs,
        supplier_code=supplier_code,
    )


def _server_payment_link_amount(
    request: Request,
    *,
    invoice_id: str,
    payload: PaymentLinkRequest,
    actor_id: str,
) -> Decimal:
    """Read the immutable effect shape before bounded settlement authorization."""

    return execute_postgres_payables(
        request,
        lambda repository, _scope: PostgresPayablesPaymentLinkRepository(
            repository.connection, repository.tenant_id
        ).authorization_amount(
            invoice_id,
            finance_effect_id=payload.finance_effect_id,
            ap_account_id=payload.ap_account_id,
            cash_account_id=payload.cash_account_id,
            expected_invoice_version=payload.expected_invoice_version,
            command_id=payload.command_id,
            actor_label=actor_id,
        ),
        object_refs=(("invoice", invoice_id),),
    )


def _server_payment_link_reversal_amount(
    request: Request,
    *,
    invoice_id: str,
    payment_link_id: str,
    payload: PaymentLinkReversalRequest,
    actor_id: str,
) -> Decimal:
    """Read the exact posted reversal amount before scoped ABAC evaluation."""

    return execute_postgres_payables(
        request,
        lambda repository, _scope: PostgresPayablesPaymentLinkRepository(
            repository.connection, repository.tenant_id
        ).authorization_reversal_amount(
            invoice_id,
            payment_link_id=payment_link_id,
            reversal_finance_effect_id=payload.reversal_finance_effect_id,
            expected_invoice_version=payload.expected_invoice_version,
            command_id=payload.command_id,
            actor_label=actor_id,
        ),
        object_refs=(("invoice", invoice_id),),
    )


@router.post("/suppliers")
def save_supplier(
    request: Request,
    payload: SupplierRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        values = payload.model_dump()
        values["actor_label"] = current_user.id
        record = _server_call(
            request,
            frozenset({"payables.manage"}),
            lambda repository, scope: repository.upsert_supplier(
                **{**values, "workspace": scope.workspace_id, "organization_code": scope.organization_code or payload.organization_code, "entity_code": scope.entity_code or payload.entity_code}
            ),
        )
        return project_payables_supplier(record).visible
    try:
        record = PayablesService(_local_connection(connection)).upsert_supplier(
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_supplier_save_failed", exc) from exc
    return project_payables_supplier(record).visible


@router.get("/suppliers")
def list_suppliers(
    request: Request,
    current_user: PayablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_payables_enabled(request):
        records = _server_call(
            request,
            frozenset({"payables.read", "payables.manage", "payables.match", "payables.approve"}),
            lambda repository, scope: repository.list_suppliers(workspace=scope.workspace_id, status=status),
        )
        return {"suppliers": [project_payables_supplier(record).visible for record in records[offset : offset + limit]], "pagination": {"limit": limit, "offset": offset, "total": len(records)}}
    try:
        records = PayablesService(_local_connection(connection)).list_suppliers(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_supplier_list_failed", exc) from exc
    return {
        "suppliers": [project_payables_supplier(record).visible for record in records[offset : offset + limit]],
        "pagination": {"limit": limit, "offset": offset, "total": len(records)},
    }


@router.post("/purchase-orders")
def create_purchase_order(
    request: Request,
    payload: PurchaseOrderRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        values = payload.model_dump(exclude={"lines"})
        values.update(lines=[PurchaseOrderLineInput(**line.model_dump()) for line in payload.lines], actor_label=current_user.id)
        record = _server_call(
            request,
            frozenset({"payables.manage"}),
            lambda repository, scope: repository.create_purchase_order(
                **{**values, "workspace": scope.workspace_id, "organization_code": scope.organization_code or payload.organization_code, "entity_code": scope.entity_code or payload.entity_code}
            ),
        )
        return project_payables_purchase_order(record).visible
    try:
        record = PayablesService(_local_connection(connection)).create_purchase_order(
            **payload.model_dump(exclude={"lines"}),
            lines=[PurchaseOrderLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_purchase_order_create_failed", exc) from exc
    return project_payables_purchase_order(record).visible


@router.post("/purchase-orders/{purchase_order_id}/submit")
def submit_purchase_order(
    purchase_order_id: str,
    request: Request,
    payload: VersionRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        record = _server_call(
            request,
            frozenset({"payables.manage"}),
            lambda repository, _scope: repository.submit_purchase_order(purchase_order_id, expected_version=payload.expected_version, actor_label=current_user.id),
            object_refs=(("purchase_order", purchase_order_id),),
        )
        return project_payables_purchase_order(record).visible
    try:
        record = PayablesService(_local_connection(connection)).submit_purchase_order(
            purchase_order_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_purchase_order_submit_failed", exc) from exc
    return project_payables_purchase_order(record).visible


@router.post("/purchase-orders/{purchase_order_id}/approve")
def approve_purchase_order(
    purchase_order_id: str,
    request: Request,
    payload: VersionRequest,
    current_user: PayablesApprove,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        record = _server_call(
            request,
            frozenset({"payables.approve"}),
            lambda repository, _scope: repository.approve_purchase_order(purchase_order_id, expected_version=payload.expected_version, actor_label=current_user.id),
            object_refs=(("purchase_order", purchase_order_id),),
        )
        return project_payables_purchase_order(record).visible
    try:
        record = PayablesService(_local_connection(connection)).approve_purchase_order(
            purchase_order_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_purchase_order_approve_failed", exc) from exc
    return project_payables_purchase_order(record).visible


@router.post("/receipts")
def post_receipt(
    request: Request,
    payload: ReceiptRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        values = payload.model_dump()
        values["actor_label"] = current_user.id
        record = _server_call(
            request,
            frozenset({"payables.manage"}),
            lambda repository, scope: repository.post_receipt(**{**values, "workspace": scope.workspace_id}),
            object_refs=(("purchase_order", payload.purchase_order_id),),
        )
        return project_payables_receipt(record).visible
    try:
        record = PayablesService(_local_connection(connection)).post_receipt(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_receipt_post_failed", exc) from exc
    return project_payables_receipt(record).visible


@router.post("/invoices")
def create_supplier_invoice(
    request: Request,
    payload: SupplierInvoiceRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        values = payload.model_dump(exclude={"lines"})
        values.update(lines=[SupplierInvoiceLineInput(**line.model_dump()) for line in payload.lines], actor_label=current_user.id)
        record = _server_call(
            request,
            frozenset({"payables.manage"}),
            lambda repository, scope: repository.create_supplier_invoice(
                **{**values, "workspace": scope.workspace_id, "organization_code": scope.organization_code or payload.organization_code, "entity_code": scope.entity_code or payload.entity_code}
            ),
            amount=Decimal(payload.total_minor),
            supplier_code=payload.supplier_code,
        )
        return project_payables_supplier_invoice(record).visible
    try:
        record = PayablesService(_local_connection(connection)).create_supplier_invoice(
            **payload.model_dump(exclude={"lines"}),
            lines=[SupplierInvoiceLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_create_failed", exc) from exc
    return project_payables_supplier_invoice(record).visible


@router.get("/invoices")
def list_supplier_invoices(
    request: Request,
    current_user: PayablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_payables_enabled(request):
        records = _server_call(
            request,
            frozenset({"payables.read", "payables.manage", "payables.match", "payables.approve"}),
            lambda repository, scope: repository.list_supplier_invoices(workspace=scope.workspace_id, status=status),
        )
        return {"invoices": [project_payables_supplier_invoice(record).visible for record in records[offset : offset + limit]], "pagination": {"limit": limit, "offset": offset, "total": len(records)}}
    try:
        records = PayablesService(_local_connection(connection)).list_supplier_invoices(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_list_failed", exc) from exc
    return {
        "invoices": [project_payables_supplier_invoice(record).visible for record in records[offset : offset + limit]],
        "pagination": {"limit": limit, "offset": offset, "total": len(records)},
    }


@router.post("/invoices/{invoice_id}/submit")
def submit_supplier_invoice(
    invoice_id: str,
    request: Request,
    payload: VersionRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        record = _server_call(
            request,
            frozenset({"payables.manage"}),
            lambda repository, _scope: repository.submit_supplier_invoice(invoice_id, expected_version=payload.expected_version, actor_label=current_user.id),
            object_refs=(("invoice", invoice_id),),
        )
        return project_payables_supplier_invoice(record).visible
    try:
        record = PayablesService(_local_connection(connection)).submit_supplier_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_submit_failed", exc) from exc
    return project_payables_supplier_invoice(record).visible


@router.post("/invoices/{invoice_id}/match")
def match_supplier_invoice(
    invoice_id: str,
    request: Request,
    current_user: PayablesMatch,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        result = _server_call(
            request,
            frozenset({"payables.match"}),
            lambda repository, _scope: asdict(repository.run_three_way_match(invoice_id, actor_label=current_user.id)),
            object_refs=(("invoice", invoice_id),),
        )
        return project_payables_three_way_match(result).visible
    try:
        result = asdict(PayablesService(_local_connection(connection)).run_three_way_match(invoice_id, actor_label=current_user.username))
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_match_failed", exc) from exc
    return project_payables_three_way_match(result).visible


@router.post("/invoices/{invoice_id}/approve")
def approve_supplier_invoice(
    invoice_id: str,
    request: Request,
    payload: VersionRequest,
    current_user: PayablesApprove,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_payables_enabled(request):
        record = _server_call(
            request,
            frozenset({"payables.approve"}),
            lambda repository, _scope: repository.approve_supplier_invoice(invoice_id, expected_version=payload.expected_version, actor_label=current_user.id),
            object_refs=(("invoice", invoice_id),),
        )
        return project_payables_supplier_invoice(record).visible
    try:
        record = PayablesService(_local_connection(connection)).approve_supplier_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_approve_failed", exc) from exc
    return project_payables_supplier_invoice(record).visible


@router.post("/invoices/{invoice_id}/payment-links")
def link_supplier_invoice_payment(
    invoice_id: str,
    request: Request,
    payload: PaymentLinkRequest,
    current_user: PayablesSettle,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Link a reviewed manual AP/cash posting to an approved supplier invoice."""

    if server_payables_enabled(request):
        amount = _server_payment_link_amount(
            request,
            invoice_id=invoice_id,
            payload=payload,
            actor_id=current_user.id,
        )
        record = _server_call(
            request,
            frozenset({"payables.settle"}),
            lambda repository, _scope: PostgresPayablesPaymentLinkRepository(
                repository.connection, repository.tenant_id
            ).link_finance_payment(invoice_id, **payload.model_dump(), actor_label=current_user.id),
            amount=amount,
            object_refs=(("invoice", invoice_id),),
        )
        return project_payables_payment_link(record).visible
    try:
        record = PayablesPaymentLinkService(_local_connection(connection)).link_finance_payment(
            invoice_id,
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_payment_link_failed", exc) from exc
    return project_payables_payment_link(record).visible


@router.post("/invoices/{invoice_id}/payment-links/{payment_link_id}/reversal")
def reverse_supplier_invoice_payment_link(
    invoice_id: str,
    payment_link_id: str,
    request: Request,
    payload: PaymentLinkReversalRequest,
    current_user: PayablesReverse,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Append evidence that a posted Finance inverse unwound one AP allocation."""

    if server_payables_enabled(request):
        amount = _server_payment_link_reversal_amount(
            request,
            invoice_id=invoice_id,
            payment_link_id=payment_link_id,
            payload=payload,
            actor_id=current_user.id,
        )
        record = _server_call(
            request,
            frozenset({"payables.reverse"}),
            lambda repository, _scope: PostgresPayablesPaymentLinkRepository(
                repository.connection, repository.tenant_id
            ).reverse_finance_payment_link(
                invoice_id,
                payment_link_id,
                **payload.model_dump(),
                actor_label=current_user.id,
            ),
            amount=amount,
            object_refs=(("invoice", invoice_id),),
        )
        return project_payables_payment_link_reversal(record).visible
    try:
        record = PayablesPaymentLinkService(_local_connection(connection)).reverse_finance_payment_link(
            invoice_id,
            payment_link_id,
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_payment_link_reversal_failed", exc) from exc
    return project_payables_payment_link_reversal(record).visible


@router.get("/invoices/{invoice_id}/payment-links")
def list_supplier_invoice_payment_links(
    invoice_id: str,
    request: Request,
    current_user: PayablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List retained settlement evidence without exposing arbitrary effect fields."""

    if server_payables_enabled(request):
        records = _server_call(
            request,
            frozenset({"payables.read", "payables.manage", "payables.match", "payables.approve", "payables.settle", "payables.reverse"}),
            lambda repository, _scope: PostgresPayablesPaymentLinkRepository(
                repository.connection, repository.tenant_id
            ).list_payment_links(invoice_id, actor_label=current_user.id),
            object_refs=(("invoice", invoice_id),),
        )
    else:
        try:
            records = PayablesPaymentLinkService(_local_connection(connection)).list_payment_links(
                invoice_id, actor_label=current_user.username
            )
        except (DatabaseError, PlatformError) as exc:
            raise _error("payables_payment_link_list_failed", exc) from exc
    return {"payment_links": [project_payables_payment_link(record).visible for record in records]}


@router.get("/invoices/{invoice_id}/payment-link-reversals")
def list_supplier_invoice_payment_link_reversals(
    invoice_id: str,
    request: Request,
    current_user: PayablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List closed-projection evidence that retained AP allocations were unwound."""

    if server_payables_enabled(request):
        records = _server_call(
            request,
            frozenset({"payables.read", "payables.manage", "payables.match", "payables.approve", "payables.settle", "payables.reverse"}),
            lambda repository, _scope: PostgresPayablesPaymentLinkRepository(
                repository.connection, repository.tenant_id
            ).list_payment_link_reversals(invoice_id, actor_label=current_user.id),
            object_refs=(("invoice", invoice_id),),
        )
    else:
        try:
            records = PayablesPaymentLinkService(_local_connection(connection)).list_payment_link_reversals(
                invoice_id, actor_label=current_user.username
            )
        except (DatabaseError, PlatformError) as exc:
            raise _error("payables_payment_link_reversal_list_failed", exc) from exc
    return {
        "payment_link_reversals": [
            project_payables_payment_link_reversal(record).visible for record in records
        ]
    }
