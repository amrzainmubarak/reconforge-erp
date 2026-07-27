"""Authenticated Accounts Receivable and credit-control routes."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput, ReceivablesService

router = APIRouter(prefix="/receivables", tags=["receivables"])
PageLimit = Annotated[int, Query(ge=1, le=1_000)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
ReceivablesRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"})),
]
ReceivablesManage = Annotated[LocalUser, Depends(require_permission("receivables.manage"))]
ReceivablesApprove = Annotated[LocalUser, Depends(require_permission("receivables.approve"))]


class CustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    currency_code: str = Field(min_length=3, max_length=3)
    credit_limit_minor: int = Field(ge=0)
    credit_hold: bool = False
    payment_terms_days: int = Field(default=0, ge=0, le=3_650)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    entity_code: str = Field(default="", max_length=64)
    tax_identifier: str = Field(default="", max_length=160)
    status: str = Field(default="Active", max_length=32)


class InvoiceLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(default="", max_length=500)
    quantity: str = Field(min_length=1, max_length=64)
    unit_price_minor: int = Field(ge=0)
    line_total_minor: int = Field(ge=0)
    tax_minor: int = Field(default=0, ge=0)


class InvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_number: str = Field(min_length=1, max_length=100)
    customer_code: str = Field(min_length=1, max_length=64)
    invoice_date: str = Field(min_length=10, max_length=10)
    currency_code: str = Field(min_length=3, max_length=3)
    tax_minor: int = Field(default=0, ge=0)
    lines: list[InvoiceLineRequest] = Field(min_length=1, max_length=1_000)
    due_date: str = Field(default="", max_length=10)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    entity_code: str = Field(default="", max_length=64)
    idempotency_key: str = Field(default="", max_length=200)


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ApprovalRequest(VersionRequest):
    credit_override_reason: str = Field(default="", max_length=500)


class ReceiptAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: str = Field(min_length=1, max_length=160)
    amount_minor: int = Field(gt=0)


class AllocateReceiptRequest(ReceiptAllocationRequest):
    expected_version: int = Field(ge=1)


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_number: str = Field(min_length=1, max_length=64)
    customer_code: str = Field(min_length=1, max_length=64)
    receipt_date: str = Field(min_length=10, max_length=10)
    currency_code: str = Field(min_length=3, max_length=3)
    amount_minor: int = Field(gt=0)
    allocations: list[ReceiptAllocationRequest] = Field(default_factory=list, max_length=1_000)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    entity_code: str = Field(default="", max_length=64)
    idempotency_key: str = Field(default="", max_length=200)


def _error(code: str, exc: Exception, *, status_code: int = 400) -> APIError:
    return APIError(status_code=status_code, code=code, message=str(exc))


@router.post("/customers")
def save_customer(
    payload: CustomerRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).upsert_customer(**payload.model_dump(), actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_customer_save_failed", exc) from exc


@router.get("/customers")
def list_customers(
    current_user: ReceivablesRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = ReceivablesService(connection).list_customers(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_customer_list_failed", exc) from exc
    return {"customers": records[offset : offset + limit], "pagination": {"limit": limit, "offset": offset, "total": len(records)}}


@router.post("/invoices")
def create_invoice(
    payload: InvoiceRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).create_invoice(
            **payload.model_dump(exclude={"lines"}),
            lines=[ReceivableInvoiceLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_create_failed", exc) from exc


@router.get("/invoices")
def list_invoices(
    current_user: ReceivablesRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = ReceivablesService(connection).list_invoices(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_list_failed", exc) from exc
    return {"invoices": records[offset : offset + limit], "pagination": {"limit": limit, "offset": offset, "total": len(records)}}


@router.post("/invoices/{invoice_id}/submit")
def submit_invoice(
    invoice_id: str,
    payload: VersionRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).submit_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_submit_failed", exc) from exc


@router.post("/invoices/{invoice_id}/approve")
def approve_invoice(
    invoice_id: str,
    payload: ApprovalRequest,
    current_user: ReceivablesApprove,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).approve_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            credit_override_reason=payload.credit_override_reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_approve_failed", exc) from exc


@router.post("/receipts")
def post_receipt(
    payload: ReceiptRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).post_receipt(
            **payload.model_dump(exclude={"allocations"}),
            allocations=[ReceiptAllocationInput(**item.model_dump()) for item in payload.allocations],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_receipt_post_failed", exc) from exc


@router.post("/receipts/{receipt_id}/allocate")
def allocate_receipt(
    receipt_id: str,
    payload: AllocateReceiptRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).allocate_receipt(
            receipt_id,
            invoice_id=payload.invoice_id,
            amount_minor=payload.amount_minor,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_receipt_allocate_failed", exc) from exc


@router.get("/credit-exposure/{customer_code}")
def credit_exposure(
    customer_code: str,
    current_user: ReceivablesRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).credit_exposure(customer_code, workspace=workspace)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_credit_exposure_failed", exc) from exc


@router.get("/aging")
def aging_report(
    current_user: ReceivablesRead,
    connection: sqlite3.Connection = Depends(get_db),
    as_of_date: str = Query(min_length=10, max_length=10),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return ReceivablesService(connection).aging_report(workspace=workspace, as_of_date=as_of_date)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_aging_failed", exc) from exc
