"""Authenticated Accounts Payable and three-way matching routes."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.payables import PayablesService, PurchaseOrderLineInput, SupplierInvoiceLineInput

router = APIRouter(prefix="/payables", tags=["payables"])
PageLimit = Annotated[int, Query(ge=1, le=1_000)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
PayablesRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"payables.read", "payables.manage", "payables.match", "payables.approve"})),
]
PayablesManage = Annotated[LocalUser, Depends(require_permission("payables.manage"))]
PayablesMatch = Annotated[LocalUser, Depends(require_permission("payables.match"))]
PayablesApprove = Annotated[LocalUser, Depends(require_permission("payables.approve"))]


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


@router.post("/suppliers")
def save_supplier(
    payload: SupplierRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).upsert_supplier(
            **payload.model_dump(),
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_supplier_save_failed", exc) from exc


@router.get("/suppliers")
def list_suppliers(
    current_user: PayablesRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = PayablesService(connection).list_suppliers(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_supplier_list_failed", exc) from exc
    return {"suppliers": records[offset : offset + limit], "pagination": {"limit": limit, "offset": offset, "total": len(records)}}


@router.post("/purchase-orders")
def create_purchase_order(
    payload: PurchaseOrderRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).create_purchase_order(
            **payload.model_dump(exclude={"lines"}),
            lines=[PurchaseOrderLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_purchase_order_create_failed", exc) from exc


@router.post("/purchase-orders/{purchase_order_id}/submit")
def submit_purchase_order(
    purchase_order_id: str,
    payload: VersionRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).submit_purchase_order(
            purchase_order_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_purchase_order_submit_failed", exc) from exc


@router.post("/purchase-orders/{purchase_order_id}/approve")
def approve_purchase_order(
    purchase_order_id: str,
    payload: VersionRequest,
    current_user: PayablesApprove,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).approve_purchase_order(
            purchase_order_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_purchase_order_approve_failed", exc) from exc


@router.post("/receipts")
def post_receipt(
    payload: ReceiptRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).post_receipt(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_receipt_post_failed", exc) from exc


@router.post("/invoices")
def create_supplier_invoice(
    payload: SupplierInvoiceRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).create_supplier_invoice(
            **payload.model_dump(exclude={"lines"}),
            lines=[SupplierInvoiceLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_create_failed", exc) from exc


@router.get("/invoices")
def list_supplier_invoices(
    current_user: PayablesRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = PayablesService(connection).list_supplier_invoices(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_list_failed", exc) from exc
    return {"invoices": records[offset : offset + limit], "pagination": {"limit": limit, "offset": offset, "total": len(records)}}


@router.post("/invoices/{invoice_id}/submit")
def submit_supplier_invoice(
    invoice_id: str,
    payload: VersionRequest,
    current_user: PayablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).submit_supplier_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_submit_failed", exc) from exc


@router.post("/invoices/{invoice_id}/match")
def match_supplier_invoice(
    invoice_id: str,
    current_user: PayablesMatch,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return asdict(PayablesService(connection).run_three_way_match(invoice_id, actor_label=current_user.username))
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_match_failed", exc) from exc


@router.post("/invoices/{invoice_id}/approve")
def approve_supplier_invoice(
    invoice_id: str,
    payload: VersionRequest,
    current_user: PayablesApprove,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return PayablesService(connection).approve_supplier_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("payables_invoice_approve_failed", exc) from exc
