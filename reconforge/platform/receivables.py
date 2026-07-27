"""Bounded Accounts Receivable and customer credit-control foundations.

This module intentionally implements a governed local slice: customer master
data, exact minor-unit sales invoices, approval-time credit controls, posted
receipts with allocations, and deterministic aging. It does not claim to be a
statutory subledger, tax engine, dunning system, payment gateway, or ERP
write-back connector.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from reconforge.auth.rbac import same_actor
from reconforge.db.connection import DatabaseError
from reconforge.domain.models import utc_now_text
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_financial_idempotency_response,
    encode_financial_idempotency_response,
)
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    require_permission,
    rows_to_dicts,
)

CUSTOMER_STATUSES = {"Draft", "Active", "Suspended", "Closed"}
INVOICE_STATUSES = {"Draft", "Submitted", "Approved", "PartiallyPaid", "Paid", "Cancelled"}


@dataclass(frozen=True)
class ReceivableInvoiceLineInput:
    """One exact invoice line; quantities are canonical decimal text."""

    description: str
    quantity: str
    unit_price_minor: int
    line_total_minor: int
    tax_minor: int = 0


@dataclass(frozen=True)
class ReceiptAllocationInput:
    """One exact allocation from a posted receipt to an approved invoice."""

    invoice_id: str
    amount_minor: int


class ReceivablesService:
    """Local customer, invoicing, receipt allocation, credit, and aging service."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        try:
            schema = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ar_customers'",
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError("Unable to read the Accounts Receivable schema.") from exc
        if schema is None:
            raise DatabaseError("Accounts Receivable schema is not initialized. Run 'reconforge db migrate' first.")
        self.connection = connection

    def upsert_customer(
        self,
        *,
        customer_code: str,
        name: str,
        currency_code: str,
        credit_limit_minor: int,
        credit_hold: bool = False,
        payment_terms_days: int = 0,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        tax_identifier: str = "",
        status: str = "Active",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update a customer credit profile."""

        require_permission(self.connection, actor_label=actor_label, permission="receivables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        code = normalize_key(customer_code, default="")
        customer_name = normalize_text(name)
        currency = _currency(currency_code)
        limit = _minor(credit_limit_minor, field="credit limit")
        terms = _nonnegative_int(payment_terms_days, field="payment terms")
        customer_status = _allowed(status, CUSTOMER_STATUSES, "customer status")
        if not code or not customer_name:
            raise PlatformError("Customer code and name are required.")
        organization_id, legal_entity_id = self._scope_ids(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
        )
        customer_id = platform_id("ARCUS", workspace_id, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO ar_customers (
                    id, workspace_id, organization_id, legal_entity_id, customer_code, name,
                    currency_code, tax_identifier, payment_terms_days, credit_limit_minor,
                    credit_hold, status, created_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(workspace_id, customer_code)
                DO UPDATE SET
                    organization_id = excluded.organization_id,
                    legal_entity_id = excluded.legal_entity_id,
                    name = excluded.name,
                    currency_code = excluded.currency_code,
                    tax_identifier = excluded.tax_identifier,
                    payment_terms_days = excluded.payment_terms_days,
                    credit_limit_minor = excluded.credit_limit_minor,
                    credit_hold = excluded.credit_hold,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    row_version = ar_customers.row_version + 1
                """,
                (
                    customer_id,
                    workspace_id,
                    organization_id,
                    legal_entity_id,
                    code,
                    customer_name,
                    currency,
                    normalize_text(tax_identifier),
                    terms,
                    limit,
                    int(credit_hold),
                    customer_status,
                    now,
                    now,
                ),
            )
            result = self.get_customer(customer_id)
            _finalize_event(
                self.connection,
                event_id=platform_id("OBX", "ar_customer", customer_id, result["row_version"]),
                event_type="ar.customer.saved",
                aggregate_type="ar_customer",
                aggregate_id=customer_id,
                payload={"customer_id": customer_id, "customer_code": code, "status": customer_status},
                actor_label=actor_label,
                object_type="ar_customer",
                object_id=customer_id,
                action="ar_customer_saved",
                metadata={"customer_code": code, "status": customer_status},
            )
            return result
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save customer.") from exc

    def create_invoice(
        self,
        *,
        invoice_number: str,
        customer_code: str,
        invoice_date: str,
        currency_code: str,
        tax_minor: int,
        lines: Sequence[ReceivableInvoiceLineInput],
        due_date: str = "",
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create a Draft sales invoice using exact minor-unit arithmetic."""

        require_permission(self.connection, actor_label=actor_label, permission="receivables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        if idempotency_key:
            previous = self._idempotent("invoice", workspace_id, idempotency_key)
            if previous is not None:
                return previous
        number = normalize_key(invoice_number, default="")
        customer = self._customer_by_code(workspace_id, customer_code)
        currency = _currency(currency_code)
        invoice_day = _date(invoice_date, field="invoice date")
        tax = _minor(tax_minor, field="invoice tax")
        if not number or not lines:
            raise PlatformError("Invoice number and at least one line are required.")
        if str(customer["currency_code"]) != currency:
            raise PlatformError("Customer invoice currency must match the customer currency.")
        due_day = (
            _date(due_date, field="due date")
            if normalize_text(due_date)
            else invoice_day
            + timedelta(
                days=int(customer["payment_terms_days"]),
            )
        )
        if due_day < invoice_day:
            raise PlatformError("Due date cannot be before invoice date.")
        organization_id, legal_entity_id = self._scope_ids(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
        )
        normalized_lines = _normalize_lines(lines)
        subtotal = sum(line.line_total_minor for line in normalized_lines)
        if sum(line.tax_minor for line in normalized_lines) != tax:
            raise PlatformError("Invoice tax must equal the sum of invoice-line tax amounts.")
        total = subtotal + tax
        invoice_id = platform_id("ARINV", workspace_id, customer["id"], number)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO ar_invoices (
                    id, workspace_id, organization_id, legal_entity_id, customer_id, invoice_number,
                    invoice_date, due_date, currency_code, subtotal_minor, tax_minor, total_minor,
                    status, created_by, created_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?, 1)
                """,
                (
                    invoice_id,
                    workspace_id,
                    organization_id,
                    legal_entity_id,
                    customer["id"],
                    number,
                    invoice_day.isoformat(),
                    due_day.isoformat(),
                    currency,
                    subtotal,
                    tax,
                    total,
                    actor_label,
                    now,
                    now,
                ),
            )
            for line_number, line in enumerate(normalized_lines, start=1):
                self.connection.execute(
                    """
                    INSERT INTO ar_invoice_lines (
                        id, invoice_id, line_number, description, quantity, unit_price_minor,
                        tax_minor, line_total_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        platform_id("ARINVL", invoice_id, line_number),
                        invoice_id,
                        line_number,
                        normalize_text(line.description),
                        line.quantity,
                        line.unit_price_minor,
                        line.tax_minor,
                        line.line_total_minor,
                        now,
                    ),
                )
            result = self.get_invoice(invoice_id)
            self._save_idempotency("invoice", workspace_id, idempotency_key, result)
            _finalize_event(
                self.connection,
                event_id=platform_id("OBX", "ar_invoice", invoice_id, "created"),
                event_type="ar.invoice.created",
                aggregate_type="ar_invoice",
                aggregate_id=invoice_id,
                payload={"invoice_id": invoice_id, "customer_id": str(customer["id"]), "total_minor": total},
                actor_label=actor_label,
                object_type="ar_invoice",
                object_id=invoice_id,
                action="ar_invoice_created",
                metadata={"invoice_number": number, "customer_id": str(customer["id"]), "total_minor": total},
            )
            return result
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Invoice number already exists or is invalid.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to create customer invoice.") from exc

    def submit_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        """Submit a Draft invoice for credit-controlled approval."""

        require_permission(self.connection, actor_label=actor_label, permission="receivables.manage")
        self._transition(
            invoice_id,
            from_status="Draft",
            to_status="Submitted",
            expected_version=expected_version,
            actor_label=actor_label,
            action="ar_invoice_submitted",
        )
        return self.get_invoice(invoice_id)

    def approve_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        credit_override_reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Approve a submitted invoice after customer status, hold, and limit checks."""

        require_permission(self.connection, actor_label=actor_label, permission="receivables.approve")
        invoice = self.get_invoice(invoice_id)
        if str(invoice["status"]) != "Submitted":
            raise PlatformError("Only a submitted receivable invoice can be approved.")
        if same_actor(invoice.get("created_by"), actor_label):
            raise PlatformError("Separation of duties conflict: invoice creator cannot approve the same invoice.")
        customer = self.get_customer(str(invoice["customer_id"]))
        exposure = self._customer_exposure(str(customer["id"]), exclude_invoice_id=invoice_id)
        hold = bool(customer["credit_hold"])
        limit_breach = exposure + int(invoice["total_minor"]) > int(customer["credit_limit_minor"])
        override_reason = normalize_text(credit_override_reason)
        if hold or limit_breach:
            if not override_reason:
                reason = "customer is on credit hold" if hold else "customer credit limit would be exceeded"
                raise PlatformError(f"Credit control blocked invoice approval: {reason}.")
            require_permission(self.connection, actor_label=actor_label, permission="receivables.credit_override")
        now = utc_now_text()
        try:
            cursor = self.connection.execute(
                """
                UPDATE ar_invoices
                SET status = 'Approved', approved_by = ?, approved_at = ?, credit_override_reason = ?,
                    updated_at = ?, row_version = row_version + 1
                WHERE id = ? AND status = 'Submitted' AND row_version = ?
                """,
                (actor_label, now, override_reason, now, invoice_id, expected_version),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                raise PlatformError("Invoice changed concurrently or is not ready for approval.")
            result = self.get_invoice(invoice_id)
            _finalize_event(
                self.connection,
                event_id=platform_id("OBX", "ar_invoice", invoice_id, "approved", expected_version),
                event_type="ar.invoice.approved",
                aggregate_type="ar_invoice",
                aggregate_id=invoice_id,
                payload={
                    "invoice_id": invoice_id,
                    "actor": actor_label,
                    "credit_override": bool(override_reason),
                },
                actor_label=actor_label,
                object_type="ar_invoice",
                object_id=invoice_id,
                action="ar_invoice_approved",
                metadata={
                    "customer_id": str(invoice["customer_id"]),
                    "total_minor": int(invoice["total_minor"]),
                    "exposure_before_minor": exposure,
                    "credit_override": bool(override_reason),
                    "credit_override_reason": override_reason,
                },
            )
            return result
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to approve customer invoice.") from exc

    def post_receipt(
        self,
        *,
        receipt_number: str,
        customer_code: str,
        receipt_date: str,
        currency_code: str,
        amount_minor: int,
        allocations: Sequence[ReceiptAllocationInput] = (),
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Post a receipt and atomically allocate it to approved invoices."""

        require_permission(self.connection, actor_label=actor_label, permission="receivables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        if idempotency_key:
            previous = self._idempotent("receipt", workspace_id, idempotency_key)
            if previous is not None:
                return previous
        number = normalize_key(receipt_number, default="")
        customer = self._customer_by_code(workspace_id, customer_code)
        currency = _currency(currency_code)
        amount = _positive_minor(amount_minor, field="receipt amount")
        receipt_day = _date(receipt_date, field="receipt date")
        if not number:
            raise PlatformError("Receipt number is required.")
        if str(customer["currency_code"]) != currency:
            raise PlatformError("Receipt currency must match the customer currency.")
        organization_id, legal_entity_id = self._scope_ids(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
        )
        normalized_allocations = _normalize_allocations(allocations)
        if sum(item.amount_minor for item in normalized_allocations) > amount:
            raise PlatformError("Receipt allocations cannot exceed the receipt amount.")
        receipt_id = platform_id("ARREC", workspace_id, number)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO ar_receipts (
                    id, workspace_id, organization_id, legal_entity_id, customer_id, receipt_number,
                    receipt_date, currency_code, amount_minor, status, created_by, posted_by, posted_at,
                    created_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Posted', ?, ?, ?, ?, ?, 1)
                """,
                (
                    receipt_id,
                    workspace_id,
                    organization_id,
                    legal_entity_id,
                    customer["id"],
                    number,
                    receipt_day.isoformat(),
                    currency,
                    amount,
                    actor_label,
                    actor_label,
                    now,
                    now,
                    now,
                ),
            )
            for allocation in normalized_allocations:
                self._insert_allocation(
                    workspace_id=workspace_id,
                    receipt_id=receipt_id,
                    customer_id=str(customer["id"]),
                    currency=currency,
                    allocation=allocation,
                    now=now,
                )
            self._save_idempotency("receipt", workspace_id, idempotency_key, self.get_receipt(receipt_id))
            result = self.get_receipt(receipt_id)
            _finalize_event(
                self.connection,
                event_id=platform_id("OBX", "ar_receipt", receipt_id, "posted"),
                event_type="ar.receipt.posted",
                aggregate_type="ar_receipt",
                aggregate_id=receipt_id,
                payload={"receipt_id": receipt_id, "customer_id": str(customer["id"]), "amount_minor": amount},
                actor_label=actor_label,
                object_type="ar_receipt",
                object_id=receipt_id,
                action="ar_receipt_posted",
                metadata={
                    "receipt_number": number,
                    "allocation_count": len(normalized_allocations),
                    "amount_minor": amount,
                },
            )
            return result
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Receipt number already exists or allocation is invalid.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to post customer receipt.") from exc

    def allocate_receipt(
        self,
        receipt_id: str,
        *,
        invoice_id: str,
        amount_minor: int,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Allocate additional unapplied receipt value with optimistic concurrency."""

        require_permission(self.connection, actor_label=actor_label, permission="receivables.manage")
        receipt = self.get_receipt(receipt_id)
        if str(receipt["status"]) != "Posted":
            raise PlatformError("Only posted receipts can be allocated.")
        if int(receipt["row_version"]) != expected_version:
            raise PlatformError("Receipt changed concurrently.")
        allocation = ReceiptAllocationInput(invoice_id=invoice_id, amount_minor=amount_minor)
        now = utc_now_text()
        try:
            self._insert_allocation(
                workspace_id=str(receipt["workspace_id"]),
                receipt_id=receipt_id,
                customer_id=str(receipt["customer_id"]),
                currency=str(receipt["currency_code"]),
                allocation=_normalize_allocations([allocation])[0],
                now=now,
            )
            cursor = self.connection.execute(
                "UPDATE ar_receipts SET updated_at = ?, row_version = row_version + 1 WHERE id = ? AND row_version = ?",
                (now, receipt_id, expected_version),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                raise PlatformError("Receipt changed concurrently.")
            result = self.get_receipt(receipt_id)
            _finalize_event(
                self.connection,
                event_id=platform_id("OBX", "ar_receipt", receipt_id, "allocated", expected_version, invoice_id),
                event_type="ar.receipt.allocated",
                aggregate_type="ar_receipt",
                aggregate_id=receipt_id,
                payload={"receipt_id": receipt_id, "invoice_id": invoice_id, "amount_minor": amount_minor},
                actor_label=actor_label,
                object_type="ar_receipt",
                object_id=receipt_id,
                action="ar_receipt_allocated",
                metadata={"invoice_id": invoice_id, "amount_minor": amount_minor},
            )
            return result
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to allocate customer receipt.") from exc

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM ar_customers WHERE id = ?", (customer_id,)).fetchone()
        if row is None:
            raise PlatformError("Customer not found.")
        return dict(row)

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM ar_invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise PlatformError("Customer invoice not found.")
        result = dict(row)
        result["lines"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ar_invoice_lines WHERE invoice_id = ? ORDER BY line_number, id",
                (invoice_id,),
            ).fetchall(),
        )
        result["allocated_minor"] = self._invoice_allocated(invoice_id)
        result["outstanding_minor"] = max(int(result["total_minor"]) - int(result["allocated_minor"]), 0)
        return result

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM ar_receipts WHERE id = ?", (receipt_id,)).fetchone()
        if row is None:
            raise PlatformError("Customer receipt not found.")
        result = dict(row)
        result["allocations"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ar_receipt_allocations WHERE receipt_id = ? ORDER BY invoice_id, id",
                (receipt_id,),
            ).fetchall(),
        )
        result["allocated_minor"] = sum(int(item["amount_minor"]) for item in result["allocations"])
        result["unallocated_minor"] = int(result["amount_minor"]) - int(result["allocated_minor"])
        return result

    def list_customers(self, *, workspace: str = "", status: str = "") -> list[dict[str, Any]]:
        workspace_id = ensure_workspace(self.connection, workspace or "default")
        return rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ar_customers WHERE workspace_id = ? AND (? = '' OR status = ?) ORDER BY customer_code, id",
                (workspace_id, status, status),
            ).fetchall(),
        )

    def list_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        workspace_id = ensure_workspace(self.connection, workspace)
        rows = self.connection.execute(
            """
            SELECT * FROM ar_invoices
            WHERE workspace_id = ? AND (? = '' OR status = ?)
            ORDER BY invoice_date, invoice_number, id
            """,
            (workspace_id, status, status),
        ).fetchall()
        return [self.get_invoice(str(row["id"])) for row in rows]

    def credit_exposure(self, customer_code: str, *, workspace: str = "default") -> dict[str, Any]:
        workspace_id = ensure_workspace(self.connection, workspace)
        customer = self._customer_by_code(workspace_id, customer_code)
        exposure = self._customer_exposure(str(customer["id"]))
        limit = int(customer["credit_limit_minor"])
        return {
            "customer_id": str(customer["id"]),
            "customer_code": str(customer["customer_code"]),
            "currency_code": str(customer["currency_code"]),
            "credit_limit_minor": limit,
            "exposure_minor": exposure,
            "available_credit_minor": limit - exposure,
            "credit_hold": bool(customer["credit_hold"]),
            "status": str(customer["status"]),
        }

    def aging_report(self, *, workspace: str = "default", as_of_date: str) -> dict[str, Any]:
        """Return deterministic open-item aging and bucket totals."""

        workspace_id = ensure_workspace(self.connection, workspace)
        as_of = _date(as_of_date, field="aging as-of date")
        rows = self.connection.execute(
            """
            SELECT invoices.*, customers.customer_code, customers.name AS customer_name
            FROM ar_invoices invoices
            JOIN ar_customers customers ON customers.id = invoices.customer_id
            WHERE invoices.workspace_id = ? AND invoices.status IN ('Approved', 'PartiallyPaid')
            ORDER BY invoices.due_date, invoices.invoice_number, invoices.id
            """,
            (workspace_id,),
        ).fetchall()
        items: list[dict[str, Any]] = []
        buckets = {"Current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        for row in rows:
            outstanding = int(row["total_minor"]) - self._invoice_allocated(str(row["id"]))
            if outstanding <= 0:
                continue
            due = _date(str(row["due_date"]), field="stored due date")
            days_overdue = max((as_of - due).days, 0)
            bucket = (
                "Current"
                if days_overdue == 0
                else "1-30"
                if days_overdue <= 30
                else "31-60"
                if days_overdue <= 60
                else "61-90"
                if days_overdue <= 90
                else "90+"
            )
            buckets[bucket] += outstanding
            items.append(
                {
                    "invoice_id": str(row["id"]),
                    "invoice_number": str(row["invoice_number"]),
                    "customer_code": str(row["customer_code"]),
                    "customer_name": str(row["customer_name"]),
                    "currency_code": str(row["currency_code"]),
                    "invoice_date": str(row["invoice_date"]),
                    "due_date": str(row["due_date"]),
                    "total_minor": int(row["total_minor"]),
                    "outstanding_minor": outstanding,
                    "days_overdue": days_overdue,
                    "bucket": bucket,
                },
            )
        return {
            "as_of_date": as_of.isoformat(),
            "items": items,
            "bucket_totals_minor": buckets,
            "total_outstanding_minor": sum(buckets.values()),
        }

    def _insert_allocation(
        self,
        *,
        workspace_id: str,
        receipt_id: str,
        customer_id: str,
        currency: str,
        allocation: ReceiptAllocationInput,
        now: str,
    ) -> None:
        invoice = self.get_invoice(allocation.invoice_id)
        if str(invoice["workspace_id"]) != workspace_id:
            raise PlatformError("Invoice belongs to a different workspace.")
        if str(invoice["customer_id"]) != customer_id:
            raise PlatformError("Receipt and invoice customers must match.")
        if str(invoice["currency_code"]) != currency:
            raise PlatformError("Receipt and invoice currencies must match.")
        if str(invoice["status"]) not in {"Approved", "PartiallyPaid"}:
            raise PlatformError("Only approved or partially paid invoices can receive allocations.")
        if int(invoice["outstanding_minor"]) < allocation.amount_minor:
            raise PlatformError("Allocation exceeds the invoice outstanding balance.")
        existing_receipt = self.connection.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) AS allocated FROM ar_receipt_allocations WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        receipt = self.connection.execute("SELECT amount_minor FROM ar_receipts WHERE id = ?", (receipt_id,)).fetchone()
        if receipt is None or int(existing_receipt["allocated"]) + allocation.amount_minor > int(
            receipt["amount_minor"]
        ):
            raise PlatformError("Receipt allocations cannot exceed the receipt amount.")
        existing_allocation = self.connection.execute(
            "SELECT id, amount_minor FROM ar_receipt_allocations WHERE receipt_id = ? AND invoice_id = ?",
            (receipt_id, allocation.invoice_id),
        ).fetchone()
        if existing_allocation is None:
            self.connection.execute(
                "INSERT INTO ar_receipt_allocations (id, workspace_id, receipt_id, invoice_id, amount_minor, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    platform_id("ARALLOC", receipt_id, allocation.invoice_id),
                    workspace_id,
                    receipt_id,
                    allocation.invoice_id,
                    allocation.amount_minor,
                    now,
                ),
            )
        else:
            self.connection.execute(
                "UPDATE ar_receipt_allocations SET amount_minor = amount_minor + ? WHERE id = ?",
                (allocation.amount_minor, existing_allocation["id"]),
            )
        total_allocated = self._invoice_allocated(allocation.invoice_id)
        status = "Paid" if total_allocated >= int(invoice["total_minor"]) else "PartiallyPaid"
        self.connection.execute(
            "UPDATE ar_invoices SET status = ?, updated_at = ?, row_version = row_version + 1 WHERE id = ?",
            (status, now, allocation.invoice_id),
        )

    def _transition(
        self,
        invoice_id: str,
        *,
        from_status: str,
        to_status: str,
        expected_version: int,
        actor_label: str,
        action: str,
    ) -> None:
        if expected_version < 1:
            raise PlatformError("Expected row version must be positive.")
        now = utc_now_text()
        try:
            cursor = self.connection.execute(
                """
                UPDATE ar_invoices
                SET status = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ? AND status = ? AND row_version = ?
                """,
                (to_status, now, invoice_id, from_status, expected_version),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                raise PlatformError("Invoice changed concurrently or is not in the expected lifecycle state.")
            _finalize_event(
                self.connection,
                event_id=platform_id("OBX", "ar_invoice", invoice_id, action, expected_version),
                event_type=f"ar.invoice.{action.removeprefix('ar_invoice_')}",
                aggregate_type="ar_invoice",
                aggregate_id=invoice_id,
                payload={"from_status": from_status, "to_status": to_status, "actor": actor_label},
                actor_label=actor_label,
                object_type="ar_invoice",
                object_id=invoice_id,
                action=action,
                metadata={"from_status": from_status, "to_status": to_status, "expected_version": expected_version},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to transition customer invoice.") from exc

    def _customer_by_code(self, workspace_id: str, customer_code: str) -> dict[str, Any]:
        code = normalize_key(customer_code, default="")
        row = self.connection.execute(
            "SELECT * FROM ar_customers WHERE workspace_id = ? AND customer_code = ?",
            (workspace_id, code),
        ).fetchone()
        if row is None:
            raise PlatformError("Customer not found in the requested workspace.")
        if str(row["status"]) != "Active":
            raise PlatformError("Customer is not Active.")
        return dict(row)

    def _scope_ids(
        self, workspace_id: str, *, organization_code: str = "", entity_code: str = ""
    ) -> tuple[str | None, str | None]:
        organization_id: str | None = None
        legal_entity_id: str | None = None
        org_code = normalize_key(organization_code, default="")
        if org_code:
            row = self.connection.execute(
                "SELECT * FROM organizations WHERE workspace_id = ? AND organization_code = ?",
                (workspace_id, org_code),
            ).fetchone()
            if row is None:
                raise PlatformError("Organization was not found in the requested workspace.")
            organization_id = str(row["id"])
            entity = normalize_key(entity_code, default="")
            if entity:
                entity_row = self.connection.execute(
                    "SELECT * FROM legal_entities WHERE organization_id = ? AND entity_code = ?",
                    (organization_id, entity),
                ).fetchone()
                if entity_row is None:
                    raise PlatformError("Legal entity was not found in the requested organization.")
                legal_entity_id = str(entity_row["id"])
        elif normalize_text(entity_code):
            raise PlatformError("Organization is required when a legal entity is supplied.")
        return organization_id, legal_entity_id

    def _customer_exposure(self, customer_id: str, *, exclude_invoice_id: str = "") -> int:
        row = self.connection.execute(
            """
            SELECT COALESCE(SUM(invoices.total_minor), 0) AS total,
                   COALESCE(SUM(allocations.allocated), 0) AS allocated
            FROM ar_invoices invoices
            LEFT JOIN (
                SELECT invoice_id, SUM(amount_minor) AS allocated
                FROM ar_receipt_allocations
                GROUP BY invoice_id
            ) allocations ON allocations.invoice_id = invoices.id
            WHERE invoices.customer_id = ?
              AND invoices.status IN ('Approved', 'PartiallyPaid')
              AND invoices.id <> ?
            """,
            (customer_id, exclude_invoice_id),
        ).fetchone()
        return max(int(row["total"]) - int(row["allocated"]), 0)

    def _invoice_allocated(self, invoice_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) AS allocated FROM ar_receipt_allocations WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        return int(row["allocated"])

    def _idempotent(self, operation: str, workspace_id: str, key: str) -> dict[str, Any] | None:
        normalized = normalize_text(key)
        if not normalized:
            return None
        row = self.connection.execute(
            "SELECT response_json FROM ar_idempotency_keys WHERE scope = ? AND idempotency_key = ?",
            (f"{operation}:{workspace_id}", normalized),
        ).fetchone()
        if row is None:
            return None
        try:
            value = decode_financial_idempotency_response(row["response_json"]).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored receivables idempotency response is invalid.") from exc
        return value

    def _save_idempotency(self, operation: str, workspace_id: str, key: str, result: dict[str, Any]) -> None:
        normalized = normalize_text(key)
        if not normalized:
            return
        try:
            document = encode_financial_idempotency_response(result)
        except PersistedJsonError as exc:
            raise PlatformError("Receivables idempotency response failed safety validation.") from exc
        self.connection.execute(
            "INSERT INTO ar_idempotency_keys (scope, idempotency_key, response_json, created_at) VALUES (?, ?, ?, ?)",
            (f"{operation}:{workspace_id}", normalized, document.text, utc_now_text()),
        )


def _finalize_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    actor_label: str,
    object_type: str,
    object_id: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append AR outbox/audit evidence and commit atomically."""

    try:
        append_outbox_event(
            connection,
            event_id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        commit_audited(
            connection,
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )
    except (PlatformError, sqlite3.DatabaseError):
        connection.rollback()
        raise


def _currency(value: str) -> str:
    currency = normalize_key(value, default="").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise PlatformError("Currency code must be a three-letter alphabetic code.")
    return currency


def _minor(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise PlatformError(f"Invalid minor-unit value in field '{field}'.")
    try:
        result = value if isinstance(value, int) else int(str(value).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlatformError(f"Invalid minor-unit value in field '{field}'.") from exc
    if result < 0:
        raise PlatformError(f"Minor-unit value in field '{field}' cannot be negative.")
    return result


def _positive_minor(value: object, *, field: str) -> int:
    result = _minor(value, field=field)
    if result <= 0:
        raise PlatformError(f"Minor-unit value in field '{field}' must be positive.")
    return result


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise PlatformError(f"Invalid integer value in field '{field}'.")
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlatformError(f"Invalid integer value in field '{field}'.") from exc
    if result < 0:
        raise PlatformError(f"Integer value in field '{field}' cannot be negative.")
    return result


def _date(value: str, *, field: str) -> date:
    try:
        return date.fromisoformat(normalize_text(value))
    except ValueError as exc:
        raise PlatformError(f"Invalid ISO date in field '{field}'.") from exc


def _quantity(value: object, *, field: str) -> str:
    try:
        quantity = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PlatformError(f"Invalid quantity in field '{field}'.") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise PlatformError(f"Quantity in field '{field}' must be finite and positive.")
    return format(quantity.normalize(), "f")


def _rounded_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalize_lines(lines: Sequence[ReceivableInvoiceLineInput]) -> list[ReceivableInvoiceLineInput]:
    normalized: list[ReceivableInvoiceLineInput] = []
    for number, line in enumerate(lines, start=1):
        quantity = _quantity(line.quantity, field=f"invoice line {number} quantity")
        unit_price = _minor(line.unit_price_minor, field=f"invoice line {number} unit price")
        line_total = _minor(line.line_total_minor, field=f"invoice line {number} total")
        tax = _minor(line.tax_minor, field=f"invoice line {number} tax")
        if _rounded_minor(Decimal(quantity) * Decimal(unit_price)) != line_total:
            raise PlatformError(f"Invoice line {number} total does not equal quantity multiplied by unit price.")
        normalized.append(
            ReceivableInvoiceLineInput(
                description=normalize_text(line.description),
                quantity=quantity,
                unit_price_minor=unit_price,
                line_total_minor=line_total,
                tax_minor=tax,
            ),
        )
    return normalized


def _normalize_allocations(allocations: Sequence[ReceiptAllocationInput]) -> list[ReceiptAllocationInput]:
    normalized: list[ReceiptAllocationInput] = []
    seen: set[str] = set()
    for allocation in allocations:
        invoice_id = normalize_key(allocation.invoice_id, default="")
        if not invoice_id or invoice_id in seen:
            raise PlatformError("Receipt allocations must contain each invoice at most once.")
        seen.add(invoice_id)
        normalized.append(
            ReceiptAllocationInput(
                invoice_id=invoice_id,
                amount_minor=_positive_minor(allocation.amount_minor, field="allocation amount"),
            ),
        )
    return normalized


def _allowed(value: str, allowed: set[str], label: str) -> str:
    normalized = normalize_text(value)
    for candidate in allowed:
        if normalized.lower() == candidate.lower():
            return candidate
    raise PlatformError(f"Invalid {label}. Expected one of: {', '.join(sorted(allowed))}.")
