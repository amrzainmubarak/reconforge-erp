"""Authenticated Accounts Receivable and credit-control routes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
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
from reconforge.api.server_receivables import (
    ReceivablesExecutionScope,
    ReceivablesObject,
    execute_postgres_receivables,
    server_receivables_enabled,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput, ReceivablesService

router = APIRouter(prefix="/receivables", tags=["receivables"])
PageLimit = Annotated[int, Query(ge=1, le=1_000)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
ReceivablesRead = Annotated[
    LocalUser,
    Depends(
        require_any_permission(
            {"receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"}
        )
    ),
]
ReceivablesManage = Annotated[LocalUser, Depends(require_permission("receivables.manage"))]
ReceivablesApprove = Annotated[LocalUser, Depends(require_permission("receivables.approve"))]
T = TypeVar("T")


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


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(
            status_code=500,
            code="local_database_not_configured",
            message="The local Receivables database is not configured for this request.",
        )
    return connection


def _server_scope(
    request: Request,
    permissions: frozenset[str],
    *,
    amount: Decimal | None = None,
) -> RequestExecutionScope:
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
    operation: Callable[[PostgresReceivablesRepository, ReceivablesExecutionScope], T],
    *,
    amount: Decimal | None = None,
    organization_code: str = "",
    entity_code: str = "",
    object_refs: tuple[tuple[ReceivablesObject, str], ...] = (),
    customer_code: str = "",
) -> T:
    _server_scope(request, permissions, amount=amount)
    return execute_postgres_receivables(
        request,
        operation,
        organization_code=organization_code,
        entity_code=entity_code,
        object_refs=object_refs,
        customer_code=customer_code,
    )


def _record_in_scope(record: dict[str, object], scope: ReceivablesExecutionScope) -> bool:
    if scope.organization_id is not None and str(record.get("organization_id") or "") != scope.organization_id:
        return False
    return scope.legal_entity_id is None or str(record.get("legal_entity_id") or "") == scope.legal_entity_id


def _filter_records(records: list[dict[str, object]], scope: ReceivablesExecutionScope) -> list[dict[str, object]]:
    return [record for record in records if _record_in_scope(record, scope)]


def _filter_aging(result: dict[str, object], scope: ReceivablesExecutionScope) -> dict[str, object]:
    raw_items = result.get("items")
    items = [item for item in raw_items if isinstance(item, dict) and _record_in_scope(item, scope)] if isinstance(raw_items, list) else []
    if scope.organization_id is None and scope.legal_entity_id is None:
        items = raw_items if isinstance(raw_items, list) else []
    buckets = {"Current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    public_items: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bucket = str(item.get("bucket", ""))
        amount = int(item.get("outstanding_minor", 0))
        if bucket in buckets:
            buckets[bucket] += amount
        public_items.append({key: value for key, value in item.items() if key not in {"organization_id", "legal_entity_id"}})
    return {
        **result,
        "items": public_items,
        "bucket_totals_minor": buckets,
        "total_outstanding_minor": sum(buckets.values()),
    }


@router.post("/customers")
def save_customer(
    request: Request,
    payload: CustomerRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_receivables_enabled(request):
        values = payload.model_dump()
        values.update(
            actor_label=current_user.id,
        )
        return _server_call(
            request,
            frozenset({"receivables.manage"}),
            lambda repository, bound_scope: repository.upsert_customer(
                **{
                    **values,
                    "workspace": bound_scope.workspace_id,
                    "organization_code": bound_scope.organization_code or payload.organization_code,
                    "entity_code": bound_scope.entity_code or payload.entity_code,
                }
            ),
        )
    try:
        return ReceivablesService(_local_connection(connection)).upsert_customer(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_customer_save_failed", exc) from exc


@router.get("/customers")
def list_customers(
    request: Request,
    current_user: ReceivablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_receivables_enabled(request):
        records = _server_call(
            request,
            frozenset({"receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"}),
            lambda repository, scope: _filter_records(
                repository.list_customers(workspace=scope.workspace_id, status=status), scope
            ),
        )
        return {
            "customers": records[offset : offset + limit],
            "pagination": {"limit": limit, "offset": offset, "total": len(records)},
        }
    try:
        records = ReceivablesService(_local_connection(connection)).list_customers(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_customer_list_failed", exc) from exc
    return {
        "customers": records[offset : offset + limit],
        "pagination": {"limit": limit, "offset": offset, "total": len(records)},
    }


@router.post("/invoices")
def create_invoice(
    request: Request,
    payload: InvoiceRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_receivables_enabled(request):
        values = payload.model_dump(exclude={"lines"})
        values.update(
            lines=[ReceivableInvoiceLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.id,
        )
        return _server_call(
            request,
            frozenset({"receivables.manage"}),
            lambda repository, bound_scope: repository.create_invoice(
                **{
                    **values,
                    "workspace": bound_scope.workspace_id,
                    "organization_code": bound_scope.organization_code or payload.organization_code,
                    "entity_code": bound_scope.entity_code or payload.entity_code,
                }
            ),
            amount=Decimal(sum(line.line_total_minor for line in payload.lines) + payload.tax_minor),
        )
    try:
        return ReceivablesService(_local_connection(connection)).create_invoice(
            **payload.model_dump(exclude={"lines"}),
            lines=[ReceivableInvoiceLineInput(**line.model_dump()) for line in payload.lines],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_create_failed", exc) from exc


@router.get("/invoices")
def list_invoices(
    request: Request,
    current_user: ReceivablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_receivables_enabled(request):
        records = _server_call(
            request,
            frozenset({"receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"}),
            lambda repository, scope: _filter_records(
                repository.list_invoices(workspace=scope.workspace_id, status=status), scope
            ),
        )
        return {
            "invoices": records[offset : offset + limit],
            "pagination": {"limit": limit, "offset": offset, "total": len(records)},
        }
    try:
        records = ReceivablesService(_local_connection(connection)).list_invoices(workspace=workspace, status=status)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_list_failed", exc) from exc
    return {
        "invoices": records[offset : offset + limit],
        "pagination": {"limit": limit, "offset": offset, "total": len(records)},
    }


@router.post("/invoices/{invoice_id}/submit")
def submit_invoice(
    invoice_id: str,
    request: Request,
    payload: VersionRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_receivables_enabled(request):
        return _server_call(
            request,
            frozenset({"receivables.manage"}),
            lambda repository, _scope: repository.submit_invoice(
                invoice_id, expected_version=payload.expected_version, actor_label=current_user.id
            ),
            object_refs=(("invoice", invoice_id),),
        )
    try:
        return ReceivablesService(_local_connection(connection)).submit_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_submit_failed", exc) from exc


@router.post("/invoices/{invoice_id}/approve")
def approve_invoice(
    invoice_id: str,
    request: Request,
    payload: ApprovalRequest,
    current_user: ReceivablesApprove,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_receivables_enabled(request):
        if payload.credit_override_reason.strip():
            _server_scope(request, frozenset({"receivables.credit_override"}))
        return _server_call(
            request,
            frozenset({"receivables.approve"}),
            lambda repository, _scope: repository.approve_invoice(
                invoice_id,
                expected_version=payload.expected_version,
                credit_override_reason=payload.credit_override_reason,
                actor_label=current_user.id,
            ),
            object_refs=(("invoice", invoice_id),),
        )
    try:
        return ReceivablesService(_local_connection(connection)).approve_invoice(
            invoice_id,
            expected_version=payload.expected_version,
            credit_override_reason=payload.credit_override_reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_invoice_approve_failed", exc) from exc


@router.post("/receipts")
def post_receipt(
    request: Request,
    payload: ReceiptRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_receivables_enabled(request):
        values = payload.model_dump(exclude={"allocations"})
        values.update(
            allocations=[ReceiptAllocationInput(**item.model_dump()) for item in payload.allocations],
            actor_label=current_user.id,
        )
        return _server_call(
            request,
            frozenset({"receivables.manage"}),
            lambda repository, bound_scope: repository.post_receipt(
                **{
                    **values,
                    "workspace": bound_scope.workspace_id,
                    "organization_code": bound_scope.organization_code or payload.organization_code,
                    "entity_code": bound_scope.entity_code or payload.entity_code,
                }
            ),
            amount=Decimal(payload.amount_minor),
            customer_code=payload.customer_code,
        )
    try:
        return ReceivablesService(_local_connection(connection)).post_receipt(
            **payload.model_dump(exclude={"allocations"}),
            allocations=[ReceiptAllocationInput(**item.model_dump()) for item in payload.allocations],
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_receipt_post_failed", exc) from exc


@router.post("/receipts/{receipt_id}/allocate")
def allocate_receipt(
    receipt_id: str,
    request: Request,
    payload: AllocateReceiptRequest,
    current_user: ReceivablesManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_receivables_enabled(request):
        return _server_call(
            request,
            frozenset({"receivables.manage"}),
            lambda repository, _scope: repository.allocate_receipt(
                receipt_id,
                invoice_id=payload.invoice_id,
                amount_minor=payload.amount_minor,
                expected_version=payload.expected_version,
                actor_label=current_user.id,
            ),
            amount=Decimal(payload.amount_minor),
            object_refs=(("receipt", receipt_id), ("invoice", payload.invoice_id)),
        )
    try:
        return ReceivablesService(_local_connection(connection)).allocate_receipt(
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
    request: Request,
    current_user: ReceivablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_receivables_enabled(request):
        return _server_call(
            request,
            frozenset({"receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"}),
            lambda repository, scope: repository.credit_exposure(customer_code, workspace=scope.workspace_id),
            customer_code=customer_code,
        )
    try:
        return ReceivablesService(_local_connection(connection)).credit_exposure(customer_code, workspace=workspace)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_credit_exposure_failed", exc) from exc


@router.get("/aging")
def aging_report(
    request: Request,
    current_user: ReceivablesRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    as_of_date: str = Query(min_length=10, max_length=10),
    workspace: str = "default",
) -> dict[str, object]:
    if server_receivables_enabled(request):
        return _server_call(
            request,
            frozenset({"receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"}),
            lambda repository, scope: _filter_aging(
                repository.aging_report(workspace=scope.workspace_id, as_of_date=as_of_date), scope
            ),
        )
    try:
        return ReceivablesService(_local_connection(connection)).aging_report(workspace=workspace, as_of_date=as_of_date)
    except (DatabaseError, PlatformError) as exc:
        raise _error("receivables_aging_failed", exc) from exc
