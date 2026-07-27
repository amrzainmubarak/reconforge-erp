"""Bounded Accounts Payable and purchase-to-pay workflow foundations.

This module deliberately implements a small, governed local slice rather than
pretending to be a complete procurement or statutory AP subledger. Monetary
values are integer minor units and quantities are canonical decimal text. All
mutations are deterministic, audited, idempotent where a key is supplied, and
use optimistic row-version checks for lifecycle transitions.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
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
from reconforge.platform.exceptions import ExceptionQueueService

SUPPLIER_STATUSES = {"Draft", "Active", "Suspended", "Closed"}
PURCHASE_ORDER_STATUSES = {"Draft", "Submitted", "Approved", "Closed", "Cancelled"}
INVOICE_STATUSES = {"Draft", "Submitted", "Matched", "Exception", "Approved", "Paid", "Rejected"}
_PAYABLE_TRANSITION_QUERIES = {
    "ap_purchase_orders": (
        """
        UPDATE ap_purchase_orders
        SET status = ?, updated_at = ?, row_version = row_version + 1
        WHERE id = ? AND status = ? AND row_version = ?
        """
    ),
    "ap_supplier_invoices": (
        """
        UPDATE ap_supplier_invoices
        SET status = ?, updated_at = ?, row_version = row_version + 1
        WHERE id = ? AND status = ? AND row_version = ?
        """
    ),
}


@dataclass(frozen=True)
class PurchaseOrderLineInput:
    """One purchase-order line using exact decimal quantity and minor-unit price."""

    item_code: str
    ordered_quantity: str
    unit_price_minor: int
    description: str = ""
    tax_minor: int = 0


@dataclass(frozen=True)
class SupplierInvoiceLineInput:
    """One supplier-invoice line linked to a purchase-order line."""

    purchase_order_line_id: str
    invoiced_quantity: str
    unit_price_minor: int
    line_total_minor: int
    description: str = ""
    tax_minor: int = 0


@dataclass(frozen=True)
class ThreeWayMatchResult:
    """Deterministic three-way match outcome."""

    match_id: str
    invoice_id: str
    purchase_order_id: str | None
    status: str
    quantity_variance: str
    price_variance_minor: int
    total_variance_minor: int
    reason: str


class PayablesService:
    """Local supplier, purchase-order, receipt, and supplier-invoice service."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        try:
            payables_schema = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ap_suppliers'",
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError("Unable to read the Accounts Payable schema.") from exc
        if payables_schema is None:
            raise DatabaseError("Accounts Payable schema is not initialized. Run 'reconforge db migrate' first.")
        self.connection = connection

    def upsert_supplier(
        self,
        *,
        supplier_code: str,
        name: str,
        currency_code: str,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        tax_identifier: str = "",
        status: str = "Active",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update a supplier master record."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        code = normalize_key(supplier_code, default="")
        supplier_name = normalize_text(name)
        currency = _currency(currency_code)
        supplier_status = _allowed(status, SUPPLIER_STATUSES, "supplier status")
        if not code or not supplier_name:
            raise PlatformError("Supplier code and name are required.")
        organization_id, legal_entity_id, _branch_id = self._scope_ids(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
        )
        supplier_id = platform_id("SUP", workspace_id, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO ap_suppliers (
                    id, workspace_id, organization_id, legal_entity_id, supplier_code,
                    name, currency_code, tax_identifier, status, created_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(workspace_id, supplier_code)
                DO UPDATE SET
                    organization_id = excluded.organization_id,
                    legal_entity_id = excluded.legal_entity_id,
                    name = excluded.name,
                    currency_code = excluded.currency_code,
                    tax_identifier = excluded.tax_identifier,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    row_version = ap_suppliers.row_version + 1
                """,
                (
                    supplier_id,
                    workspace_id,
                    organization_id,
                    legal_entity_id,
                    code,
                    supplier_name,
                    currency,
                    normalize_text(tax_identifier),
                    supplier_status,
                    now,
                    now,
                ),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save supplier.") from exc
        supplier_record = self.get_supplier(supplier_id)
        _finalize_event(
            self.connection,
            event_id=platform_id("OBX", "ap_supplier", supplier_id, supplier_record["row_version"]),
            event_type="ap.supplier.saved",
            aggregate_type="ap_supplier",
            aggregate_id=supplier_id,
            payload={"supplier_id": supplier_id, "supplier_code": code, "status": supplier_status},
            actor_label=actor_label,
            object_type="ap_supplier",
            object_id=supplier_id,
            action="ap_supplier_saved",
            metadata={"supplier_code": code, "status": supplier_status},
        )
        return supplier_record

    def create_purchase_order(
        self,
        *,
        po_number: str,
        supplier_code: str,
        order_date: str,
        currency_code: str,
        lines: Sequence[PurchaseOrderLineInput],
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        branch_code: str = "",
        expected_date: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create a Draft purchase order with exact line quantities and prices."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        if idempotency_key:
            previous = self._idempotent("purchase_order", workspace_id, idempotency_key)
            if previous is not None:
                return previous
        number = normalize_key(po_number, default="")
        supplier = self._supplier_by_code(workspace_id, supplier_code)
        currency = _currency(currency_code)
        if not number or not order_date or not lines:
            raise PlatformError("Purchase order number, order date, and at least one line are required.")
        if str(supplier["currency_code"]) != currency:
            raise PlatformError("Purchase order currency must match the supplier currency.")
        organization_id, legal_entity_id, branch_id = self._scope_ids(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
            branch_code=branch_code,
        )
        po_id = platform_id("APPO", workspace_id, number)
        now = utc_now_text()
        normalized_lines = _normalize_po_lines(lines)
        try:
            self.connection.execute(
                """
                INSERT INTO ap_purchase_orders (
                    id, workspace_id, organization_id, legal_entity_id, branch_id, supplier_id,
                    po_number, order_date, expected_date, currency_code, status, created_by,
                    created_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?, 1)
                """,
                (
                    po_id,
                    workspace_id,
                    organization_id,
                    legal_entity_id,
                    branch_id,
                    supplier["id"],
                    number,
                    order_date,
                    normalize_text(expected_date),
                    currency,
                    actor_label,
                    now,
                    now,
                ),
            )
            for line_number, line in enumerate(normalized_lines, start=1):
                self.connection.execute(
                    """
                    INSERT INTO ap_purchase_order_lines (
                        id, purchase_order_id, line_number, item_code, description,
                        ordered_quantity, unit_price_minor, tax_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        platform_id("APPOL", po_id, line_number, line.item_code),
                        po_id,
                        line_number,
                        normalize_key(line.item_code, default=""),
                        normalize_text(line.description),
                        _quantity(line.ordered_quantity, field=f"line {line_number} quantity"),
                        _minor(line.unit_price_minor, field=f"line {line_number} unit price"),
                        _minor(line.tax_minor, field=f"line {line_number} tax"),
                        now,
                    ),
                )
            result = self.get_purchase_order(po_id)
            self._save_idempotency("purchase_order", workspace_id, idempotency_key, result)
            append_outbox_event(
                self.connection,
                event_id=platform_id("OBX", "ap_purchase_order", po_id, "created"),
                event_type="ap.purchase_order.created",
                aggregate_type="ap_purchase_order",
                aggregate_id=po_id,
                payload={"purchase_order_id": po_id, "po_number": number, "workspace_id": workspace_id},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Purchase order number already exists or references are invalid.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to create purchase order.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="ap_purchase_order",
            object_id=po_id,
            action="ap_purchase_order_created",
            metadata={"po_number": number, "supplier_id": str(supplier["id"]), "line_count": len(normalized_lines)},
        )
        return result

    def submit_purchase_order(
        self,
        purchase_order_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Submit a Draft purchase order using optimistic concurrency."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.manage")
        self._transition(
            table="ap_purchase_orders",
            object_type="ap_purchase_order",
            object_id=purchase_order_id,
            from_status="Draft",
            to_status="Submitted",
            expected_version=expected_version,
            actor_label=actor_label,
            action="ap_purchase_order_submitted",
        )
        return self.get_purchase_order(purchase_order_id)

    def approve_purchase_order(
        self,
        purchase_order_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Approve a submitted purchase order."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.approve")
        order = self.get_purchase_order(purchase_order_id)
        if same_actor(order.get("created_by"), actor_label):
            raise PlatformError("Separation of duties conflict: purchase-order creator cannot approve the same order.")
        now = utc_now_text()
        try:
            cursor = self.connection.execute(
                """
                UPDATE ap_purchase_orders
                SET status = 'Approved', approved_by = ?, approved_at = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ? AND status = 'Submitted' AND row_version = ?
                """,
                (actor_label, now, now, purchase_order_id, expected_version),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                raise PlatformError("Purchase order changed concurrently or is not ready for approval.")
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to approve purchase order.") from exc
        _finalize_event(
            self.connection,
            event_id=platform_id("OBX", "ap_purchase_order", purchase_order_id, "approved", expected_version),
            event_type="ap.purchase_order.approved",
            aggregate_type="ap_purchase_order",
            aggregate_id=purchase_order_id,
            payload={"purchase_order_id": purchase_order_id, "actor": actor_label},
            actor_label=actor_label,
            object_type="ap_purchase_order",
            object_id=purchase_order_id,
            action="ap_purchase_order_approved",
        )
        return self.get_purchase_order(purchase_order_id)

    def post_receipt(
        self,
        *,
        receipt_number: str,
        purchase_order_id: str,
        receipt_date: str,
        quantities: dict[str, str],
        workspace: str = "default",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Post received quantities, rejecting over-receipt and unknown lines."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        if idempotency_key:
            previous = self._idempotent("goods_receipt", workspace_id, idempotency_key)
            if previous is not None:
                return previous
        order = self.get_purchase_order(purchase_order_id)
        if order["workspace_id"] != workspace_id or order["status"] != "Approved":
            raise PlatformError("Goods receipts require an Approved purchase order in the same workspace.")
        if not quantities:
            raise PlatformError("Goods receipt quantities are required.")
        receipt_id = platform_id("APGR", workspace_id, normalize_key(receipt_number, default=""))
        now = utc_now_text()
        line_rows = {str(row["id"]): row for row in order["lines"]}
        normalized_quantities: dict[str, str] = {}
        for line_id, raw_quantity in quantities.items():
            if line_id not in line_rows:
                raise PlatformError(f"Unknown purchase-order line: {line_id}.")
            normalized_quantities[line_id] = _quantity(raw_quantity, field=f"receipt quantity {line_id}")
        try:
            self.connection.execute(
                """
                INSERT INTO ap_goods_receipts (
                    id, workspace_id, purchase_order_id, receipt_number, receipt_date,
                    status, created_by, posted_by, posted_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'Posted', ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    workspace_id,
                    purchase_order_id,
                    normalize_key(receipt_number, default=""),
                    receipt_date,
                    actor_label,
                    actor_label,
                    now,
                    now,
                    now,
                ),
            )
            for line_id, quantity in normalized_quantities.items():
                row = line_rows[line_id]
                already_received = self._received_quantity(line_id)
                if already_received + Decimal(quantity) > Decimal(str(row["ordered_quantity"])):
                    raise PlatformError(f"Receipt exceeds ordered quantity for line {line_id}.")
                self.connection.execute(
                    """
                    INSERT INTO ap_goods_receipt_lines (id, receipt_id, purchase_order_line_id, received_quantity, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (platform_id("APGRL", receipt_id, line_id), receipt_id, line_id, quantity, now),
                )
            result = self.get_receipt(receipt_id)
            self._save_idempotency("goods_receipt", workspace_id, idempotency_key, result)
            append_outbox_event(
                self.connection,
                event_id=platform_id("OBX", "ap_goods_receipt", receipt_id, "posted"),
                event_type="ap.goods_receipt.posted",
                aggregate_type="ap_goods_receipt",
                aggregate_id=receipt_id,
                payload={
                    "receipt_id": receipt_id,
                    "purchase_order_id": purchase_order_id,
                    "workspace_id": workspace_id,
                },
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Receipt number already exists or references are invalid.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to post goods receipt.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="ap_goods_receipt",
            object_id=receipt_id,
            action="ap_goods_receipt_posted",
            metadata={"purchase_order_id": purchase_order_id, "line_count": len(normalized_quantities)},
        )
        return result

    def create_supplier_invoice(
        self,
        *,
        invoice_number: str,
        supplier_code: str,
        invoice_date: str,
        currency_code: str,
        total_minor: int,
        lines: Sequence[SupplierInvoiceLineInput],
        purchase_order_id: str = "",
        tax_minor: int = 0,
        due_date: str = "",
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create a Draft supplier invoice for a supplier and optional purchase order."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        if idempotency_key:
            previous = self._idempotent("supplier_invoice", workspace_id, idempotency_key)
            if previous is not None:
                return previous
        number = normalize_key(invoice_number, default="")
        supplier = self._supplier_by_code(workspace_id, supplier_code)
        currency = _currency(currency_code)
        total = _minor(total_minor, field="invoice total")
        tax = _minor(tax_minor, field="invoice tax")
        if not number or not invoice_date or not lines:
            raise PlatformError("Invoice number, invoice date, and at least one line are required.")
        if str(supplier["currency_code"]) != currency:
            raise PlatformError("Supplier invoice currency must match the supplier currency.")
        organization_id, legal_entity_id, _branch_id = self._scope_ids(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
        )
        po_id = normalize_text(purchase_order_id)
        po = self.get_purchase_order(po_id) if po_id else None
        if po is not None and str(po["supplier_id"]) != str(supplier["id"]):
            raise PlatformError("Supplier invoice and purchase order suppliers must match.")
        normalized_lines = _normalize_invoice_lines(lines)
        if sum(line.line_total_minor for line in normalized_lines) + tax != total:
            raise PlatformError("Invoice total must equal the sum of line totals plus invoice tax.")
        invoice_id = platform_id("APINV", workspace_id, supplier["id"], number)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO ap_supplier_invoices (
                    id, workspace_id, organization_id, legal_entity_id, supplier_id, purchase_order_id,
                    invoice_number, invoice_date, due_date, currency_code, tax_minor, total_minor,
                    status, created_by, created_at, updated_at, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?, 1)
                """,
                (
                    invoice_id,
                    workspace_id,
                    organization_id,
                    legal_entity_id,
                    supplier["id"],
                    po_id or None,
                    number,
                    invoice_date,
                    normalize_text(due_date),
                    currency,
                    tax,
                    total,
                    actor_label,
                    now,
                    now,
                ),
            )
            for line_number, line in enumerate(normalized_lines, start=1):
                if po is not None and not any(
                    str(po_line["id"]) == line.purchase_order_line_id for po_line in po["lines"]
                ):
                    raise PlatformError(
                        f"Invoice line references an unknown purchase-order line: {line.purchase_order_line_id}."
                    )
                self.connection.execute(
                    """
                    INSERT INTO ap_supplier_invoice_lines (
                        id, supplier_invoice_id, purchase_order_line_id, line_number, description,
                        invoiced_quantity, unit_price_minor, tax_minor, line_total_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        platform_id("APINVL", invoice_id, line_number, line.purchase_order_line_id),
                        invoice_id,
                        line.purchase_order_line_id or None,
                        line_number,
                        normalize_text(line.description),
                        _quantity(line.invoiced_quantity, field=f"invoice line {line_number} quantity"),
                        _minor(line.unit_price_minor, field=f"invoice line {line_number} unit price"),
                        _minor(line.tax_minor, field=f"invoice line {line_number} tax"),
                        _minor(line.line_total_minor, field=f"invoice line {line_number} total"),
                        now,
                    ),
                )
            result = self.get_supplier_invoice(invoice_id)
            self._save_idempotency("supplier_invoice", workspace_id, idempotency_key, result)
            append_outbox_event(
                self.connection,
                event_id=platform_id("OBX", "ap_supplier_invoice", invoice_id, "created"),
                event_type="ap.supplier_invoice.created",
                aggregate_type="ap_supplier_invoice",
                aggregate_id=invoice_id,
                payload={"invoice_id": invoice_id, "supplier_id": str(supplier["id"]), "workspace_id": workspace_id},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Supplier invoice number already exists or references are invalid.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to create supplier invoice.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="ap_supplier_invoice",
            object_id=invoice_id,
            action="ap_supplier_invoice_created",
            metadata={"invoice_number": number, "supplier_id": str(supplier["id"]), "total_minor": total},
        )
        return result

    def submit_supplier_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Submit a Draft supplier invoice for matching."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.manage")
        self._transition(
            table="ap_supplier_invoices",
            object_type="ap_supplier_invoice",
            object_id=invoice_id,
            from_status="Draft",
            to_status="Submitted",
            expected_version=expected_version,
            actor_label=actor_label,
            action="ap_supplier_invoice_submitted",
        )
        return self.get_supplier_invoice(invoice_id)

    def run_three_way_match(self, invoice_id: str, *, actor_label: str = "local-cli") -> ThreeWayMatchResult:
        """Compare invoice quantity/price to the linked PO and posted receipts."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.match")
        invoice = self.get_supplier_invoice(invoice_id)
        po_id = str(invoice["purchase_order_id"] or "")
        po = self.get_purchase_order(po_id) if po_id else None
        po_lines = {str(row["id"]): row for row in po["lines"]} if po is not None else {}
        quantity_variance = Decimal("0")
        price_variance = Decimal("0")
        total_variance = Decimal("0")
        reasons: list[str] = []
        if po is None:
            reasons.append("AP-3WM-MISSING-PO")
        for line in invoice["lines"]:
            line_id = str(line["purchase_order_line_id"] or "")
            po_line = po_lines.get(line_id)
            if po_line is None:
                reasons.append(f"AP-3WM-UNKNOWN-LINE:{line_id}")
                continue
            received = self._received_quantity(line_id)
            invoiced = Decimal(str(line["invoiced_quantity"]))
            quantity_variance += invoiced - received
            unit_price_delta = Decimal(int(line["unit_price_minor"])) - Decimal(int(po_line["unit_price_minor"]))
            price_variance += unit_price_delta * invoiced
            expected_total = _rounded_minor(Decimal(int(po_line["unit_price_minor"])) * invoiced)
            total_variance += Decimal(int(line["line_total_minor"])) - expected_total
            if invoiced > received:
                reasons.append(f"AP-3WM-QUANTITY:{line_id}")
            if unit_price_delta != 0:
                reasons.append(f"AP-3WM-PRICE:{line_id}")
        status = (
            "Passed"
            if not reasons and quantity_variance == 0 and price_variance == 0 and total_variance == 0
            else "Exception"
        )
        reason = ";".join(sorted(set(reasons)))
        match_id = platform_id("AP3WM", invoice_id)
        now = utc_now_text()
        quantity_text = _decimal_text(quantity_variance)
        price_minor = _rounded_minor(price_variance)
        total_minor = _rounded_minor(total_variance)
        try:
            self.connection.execute(
                """
                INSERT INTO ap_three_way_matches (
                    id, workspace_id, supplier_invoice_id, purchase_order_id, status,
                    quantity_variance, price_variance_minor, total_variance_minor, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(supplier_invoice_id)
                DO UPDATE SET
                    purchase_order_id = excluded.purchase_order_id,
                    status = excluded.status,
                    quantity_variance = excluded.quantity_variance,
                    price_variance_minor = excluded.price_variance_minor,
                    total_variance_minor = excluded.total_variance_minor,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    match_id,
                    invoice["workspace_id"],
                    invoice_id,
                    po_id or None,
                    status,
                    quantity_text,
                    price_minor,
                    total_minor,
                    reason,
                    now,
                    now,
                ),
            )
            invoice_status = "Matched" if status == "Passed" else "Exception"
            self.connection.execute(
                "UPDATE ap_supplier_invoices SET status = ?, updated_at = ?, row_version = row_version + 1 WHERE id = ?",
                (invoice_status, now, invoice_id),
            )
            if status == "Exception":
                ExceptionQueueService(self.connection, autocommit=False).upsert_exception(
                    source_type="ap_three_way_match",
                    source_id=match_id,
                    description=f"Supplier invoice three-way match exception: {reason or 'variance'}.",
                    workspace=self._workspace_name(str(invoice["workspace_id"])),
                    entity_code=str(invoice.get("legal_entity_id") or ""),
                    control_code="AP-3WM",
                    risk_rating="high" if total_minor or price_minor else "medium",
                    actor_label=actor_label,
                )
            else:
                self.connection.execute(
                    """
                    UPDATE exceptions_queue
                    SET status = 'Resolved', updated_at = ?
                    WHERE source_type = 'ap_three_way_match' AND source_id = ? AND status <> 'Resolved'
                    """,
                    (now, match_id),
                )
            append_outbox_event(
                self.connection,
                event_id=platform_id("OBX", "ap_three_way_match", match_id, status),
                event_type="ap.three_way_match.completed",
                aggregate_type="ap_three_way_match",
                aggregate_id=match_id,
                payload={"invoice_id": invoice_id, "status": status, "reason": reason},
            )
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="ap_three_way_match",
                object_id=match_id,
                action="ap_three_way_match_completed",
                metadata={"invoice_id": invoice_id, "status": status, "reason": reason},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to complete supplier invoice matching.") from exc
        return ThreeWayMatchResult(
            match_id=match_id,
            invoice_id=invoice_id,
            purchase_order_id=po_id or None,
            status=status,
            quantity_variance=quantity_text,
            price_variance_minor=price_minor,
            total_variance_minor=total_minor,
            reason=reason,
        )

    def approve_supplier_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Approve only a passed/matched invoice, enforcing optimistic concurrency."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.approve")
        invoice = self.get_supplier_invoice(invoice_id)
        if str(invoice["status"]) != "Matched":
            raise PlatformError("Only a supplier invoice with a passed three-way match can be approved.")
        if same_actor(invoice.get("created_by"), actor_label):
            raise PlatformError("Separation of duties conflict: invoice creator cannot approve the same invoice.")
        now = utc_now_text()
        try:
            cursor = self.connection.execute(
                """
                UPDATE ap_supplier_invoices
                SET status = 'Approved', approved_by = ?, approved_at = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ? AND status = 'Matched' AND row_version = ?
                """,
                (actor_label, now, now, invoice_id, expected_version),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                raise PlatformError("Supplier invoice changed concurrently or is not ready for approval.")
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to approve supplier invoice.") from exc
        _finalize_event(
            self.connection,
            event_id=platform_id("OBX", "ap_supplier_invoice", invoice_id, "approved", expected_version),
            event_type="ap.supplier_invoice.approved",
            aggregate_type="ap_supplier_invoice",
            aggregate_id=invoice_id,
            payload={"invoice_id": invoice_id, "actor": actor_label},
            actor_label=actor_label,
            object_type="ap_supplier_invoice",
            object_id=invoice_id,
            action="ap_supplier_invoice_approved",
        )
        return self.get_supplier_invoice(invoice_id)

    def get_supplier(self, supplier_id: str) -> dict[str, Any]:
        """Return one supplier."""

        row = self.connection.execute("SELECT * FROM ap_suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if row is None:
            raise PlatformError("Supplier not found.")
        return dict(row)

    def get_purchase_order(self, purchase_order_id: str) -> dict[str, Any]:
        """Return a purchase order and deterministically ordered lines."""

        row = self.connection.execute("SELECT * FROM ap_purchase_orders WHERE id = ?", (purchase_order_id,)).fetchone()
        if row is None:
            raise PlatformError("Purchase order not found.")
        result = dict(row)
        result["lines"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ap_purchase_order_lines WHERE purchase_order_id = ? ORDER BY line_number, id",
                (purchase_order_id,),
            ).fetchall(),
        )
        return result

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        """Return one posted goods receipt."""

        row = self.connection.execute("SELECT * FROM ap_goods_receipts WHERE id = ?", (receipt_id,)).fetchone()
        if row is None:
            raise PlatformError("Goods receipt not found.")
        result = dict(row)
        result["lines"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ap_goods_receipt_lines WHERE receipt_id = ? ORDER BY id",
                (receipt_id,),
            ).fetchall(),
        )
        return result

    def get_supplier_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Return a supplier invoice and deterministic lines/match."""

        row = self.connection.execute("SELECT * FROM ap_supplier_invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise PlatformError("Supplier invoice not found.")
        result = dict(row)
        result["lines"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ap_supplier_invoice_lines WHERE supplier_invoice_id = ? ORDER BY line_number, id",
                (invoice_id,),
            ).fetchall(),
        )
        match = self.connection.execute(
            "SELECT * FROM ap_three_way_matches WHERE supplier_invoice_id = ?", (invoice_id,)
        ).fetchone()
        result["three_way_match"] = dict(match) if match is not None else None
        return result

    def list_suppliers(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        """List suppliers in deterministic order."""

        workspace_id = ensure_workspace(self.connection, workspace)
        return rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM ap_suppliers WHERE workspace_id = ? AND (? = '' OR status = ?) ORDER BY supplier_code, id",
                (workspace_id, status, status),
            ).fetchall(),
        )

    def list_supplier_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        """List supplier invoices in deterministic order."""

        workspace_id = ensure_workspace(self.connection, workspace)
        return rows_to_dicts(
            self.connection.execute(
                """
                SELECT * FROM ap_supplier_invoices
                WHERE workspace_id = ? AND (? = '' OR status = ?)
                ORDER BY invoice_date, invoice_number, id
                """,
                (workspace_id, status, status),
            ).fetchall(),
        )

    def _transition(
        self,
        *,
        table: str,
        object_type: str,
        object_id: str,
        from_status: str,
        to_status: str,
        expected_version: int,
        actor_label: str,
        action: str,
    ) -> None:
        if expected_version < 1:
            raise PlatformError("Expected row version must be positive.")
        transition_query = _PAYABLE_TRANSITION_QUERIES.get(table)
        if transition_query is None:
            raise PlatformError("Unsupported payable object type.")
        now = utc_now_text()
        try:
            cursor = self.connection.execute(
                transition_query,
                (to_status, now, object_id, from_status, expected_version),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                raise PlatformError("Record changed concurrently or is not in the expected lifecycle state.")
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to transition payable record.") from exc
        _finalize_event(
            self.connection,
            event_id=platform_id("OBX", object_type, object_id, action, expected_version),
            event_type=f"{object_type}.{action}",
            aggregate_type=object_type,
            aggregate_id=object_id,
            payload={"from_status": from_status, "to_status": to_status, "actor": actor_label},
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata={"from_status": from_status, "to_status": to_status, "expected_version": expected_version},
        )

    def _supplier_by_code(self, workspace_id: str, supplier_code: str) -> dict[str, Any]:
        code = normalize_key(supplier_code, default="")
        row = self.connection.execute(
            "SELECT * FROM ap_suppliers WHERE workspace_id = ? AND supplier_code = ?",
            (workspace_id, code),
        ).fetchone()
        if row is None:
            raise PlatformError("Supplier not found in the requested workspace.")
        if str(row["status"]) != "Active":
            raise PlatformError("Supplier is not Active.")
        return dict(row)

    def _scope_ids(
        self,
        workspace_id: str,
        *,
        organization_code: str = "",
        entity_code: str = "",
        branch_code: str = "",
    ) -> tuple[str | None, str | None, str | None]:
        organization_id: str | None = None
        legal_entity_id: str | None = None
        branch_id: str | None = None
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
            branch = normalize_key(branch_code, default="")
            if branch:
                branch_row = self.connection.execute(
                    "SELECT * FROM branches WHERE organization_id = ? AND branch_code = ?",
                    (organization_id, branch),
                ).fetchone()
                if branch_row is None:
                    raise PlatformError("Branch was not found in the requested organization.")
                branch_id = str(branch_row["id"])
        elif normalize_text(entity_code) or normalize_text(branch_code):
            raise PlatformError("Organization is required when a legal entity or branch is supplied.")
        return organization_id, legal_entity_id, branch_id

    def _received_quantity(self, purchase_order_line_id: str) -> Decimal:
        rows = self.connection.execute(
            """
            SELECT receipt_lines.received_quantity
            FROM ap_goods_receipt_lines receipt_lines
            JOIN ap_goods_receipts receipts ON receipts.id = receipt_lines.receipt_id
            WHERE receipt_lines.purchase_order_line_id = ? AND receipts.status = 'Posted'
            ORDER BY receipts.receipt_date, receipts.id
            """,
            (purchase_order_line_id,),
        ).fetchall()
        return sum((Decimal(str(row["received_quantity"])) for row in rows), Decimal("0"))

    def _workspace_name(self, workspace_id: str) -> str:
        row = self.connection.execute("SELECT name FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if row is None:
            raise PlatformError("Workspace not found for payable exception routing.")
        return str(row["name"])

    def _idempotent(self, operation: str, workspace_id: str, key: str) -> dict[str, Any] | None:
        normalized = normalize_text(key)
        if not normalized:
            return None
        row = self.connection.execute(
            "SELECT response_json FROM ap_idempotency_keys WHERE scope = ? AND idempotency_key = ?",
            (f"{operation}:{workspace_id}", normalized),
        ).fetchone()
        if row is None:
            return None
        try:
            value = decode_financial_idempotency_response(row["response_json"]).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored idempotency response is invalid.") from exc
        return value

    def _save_idempotency(self, operation: str, workspace_id: str, key: str, result: dict[str, Any]) -> None:
        normalized = normalize_text(key)
        if not normalized:
            return
        try:
            document = encode_financial_idempotency_response(result)
        except PersistedJsonError as exc:
            raise PlatformError("Idempotency response failed safety validation.") from exc
        self.connection.execute(
            "INSERT INTO ap_idempotency_keys (scope, idempotency_key, response_json, created_at) VALUES (?, ?, ?, ?)",
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
    """Append AP outbox/audit evidence and commit, rolling back on either failure."""

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


def _allowed(value: str, allowed: set[str], label: str) -> str:
    normalized = normalize_text(value)
    for candidate in allowed:
        if normalized.lower() == candidate.lower():
            return candidate
    raise PlatformError(f"Invalid {label}. Expected one of: {', '.join(sorted(allowed))}.")


def _currency(value: str) -> str:
    currency = normalize_key(value, default="").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise PlatformError("Currency code must be a three-letter alphabetic code.")
    return currency


def _minor(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise PlatformError(f"Invalid minor-unit value in field '{field}'.")
    try:
        if isinstance(value, int):
            result = value
        elif isinstance(value, str) and value.strip():
            result = int(value.strip())
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlatformError(f"Invalid minor-unit value in field '{field}'.") from exc
    if result < 0:
        raise PlatformError(f"Minor-unit value in field '{field}' cannot be negative.")
    return result


def _quantity(value: object, *, field: str) -> str:
    text = normalize_text(value, default="")
    if not text:
        raise PlatformError(f"Quantity in field '{field}' is required.")
    try:
        quantity = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise PlatformError(f"Invalid quantity in field '{field}'.") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise PlatformError(f"Quantity in field '{field}' must be finite and greater than zero.")
    return _decimal_text(quantity)


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _rounded_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalize_po_lines(lines: Sequence[PurchaseOrderLineInput]) -> list[PurchaseOrderLineInput]:
    result: list[PurchaseOrderLineInput] = []
    for index, line in enumerate(lines, start=1):
        if not normalize_key(line.item_code, default=""):
            raise PlatformError(f"Purchase-order line {index} requires an item code.")
        result.append(
            PurchaseOrderLineInput(
                item_code=normalize_key(line.item_code, default=""),
                ordered_quantity=_quantity(line.ordered_quantity, field=f"line {index} quantity"),
                unit_price_minor=_minor(line.unit_price_minor, field=f"line {index} unit price"),
                description=normalize_text(line.description),
                tax_minor=_minor(line.tax_minor, field=f"line {index} tax"),
            ),
        )
    return result


def _normalize_invoice_lines(lines: Sequence[SupplierInvoiceLineInput]) -> list[SupplierInvoiceLineInput]:
    result: list[SupplierInvoiceLineInput] = []
    for index, line in enumerate(lines, start=1):
        if not normalize_text(line.purchase_order_line_id):
            raise PlatformError(f"Invoice line {index} requires a purchase-order line reference.")
        result.append(
            SupplierInvoiceLineInput(
                purchase_order_line_id=normalize_text(line.purchase_order_line_id),
                invoiced_quantity=_quantity(line.invoiced_quantity, field=f"invoice line {index} quantity"),
                unit_price_minor=_minor(line.unit_price_minor, field=f"invoice line {index} unit price"),
                line_total_minor=_minor(line.line_total_minor, field=f"invoice line {index} total"),
                description=normalize_text(line.description),
                tax_minor=_minor(line.tax_minor, field=f"invoice line {index} tax"),
            ),
        )
    return result
