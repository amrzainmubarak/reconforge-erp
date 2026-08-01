"""Backend-neutral governed purchase-to-pay application boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PurchaseOrderLineInput:
    """One purchase-order line using exact quantity and minor-unit price."""

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


class PayablesRepositoryProtocol(Protocol):
    """Complete persistence and policy port for governed purchase-to-pay."""

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
    ) -> dict[str, Any]: ...
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
    ) -> dict[str, Any]: ...
    def submit_purchase_order(
        self, purchase_order_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def approve_purchase_order(
        self, purchase_order_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
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
    ) -> dict[str, Any]: ...
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
    ) -> dict[str, Any]: ...
    def submit_supplier_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def run_three_way_match(self, invoice_id: str, *, actor_label: str = "local-cli") -> ThreeWayMatchResult: ...
    def approve_supplier_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def get_supplier(self, supplier_id: str) -> dict[str, Any]: ...
    def get_purchase_order(self, purchase_order_id: str) -> dict[str, Any]: ...
    def get_receipt(self, receipt_id: str) -> dict[str, Any]: ...
    def get_supplier_invoice(self, invoice_id: str) -> dict[str, Any]: ...
    def list_suppliers(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]: ...
    def list_supplier_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]: ...


class PayablesApplicationService:
    """Coordinate purchase-to-pay use cases without a database dependency."""

    def __init__(self, repository: PayablesRepositoryProtocol) -> None:
        self.repository = repository

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
        return self.repository.upsert_supplier(
            supplier_code=supplier_code,
            name=name,
            currency_code=currency_code,
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            tax_identifier=tax_identifier,
            status=status,
            actor_label=actor_label,
        )

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
        return self.repository.create_purchase_order(
            po_number=po_number,
            supplier_code=supplier_code,
            order_date=order_date,
            currency_code=currency_code,
            lines=lines,
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            branch_code=branch_code,
            expected_date=expected_date,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
        )

    def submit_purchase_order(
        self, purchase_order_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self.repository.submit_purchase_order(
            purchase_order_id, expected_version=expected_version, actor_label=actor_label
        )

    def approve_purchase_order(
        self, purchase_order_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self.repository.approve_purchase_order(
            purchase_order_id, expected_version=expected_version, actor_label=actor_label
        )

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
        return self.repository.post_receipt(
            receipt_number=receipt_number,
            purchase_order_id=purchase_order_id,
            receipt_date=receipt_date,
            quantities=quantities,
            workspace=workspace,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
        )

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
        return self.repository.create_supplier_invoice(
            invoice_number=invoice_number,
            supplier_code=supplier_code,
            invoice_date=invoice_date,
            currency_code=currency_code,
            total_minor=total_minor,
            lines=lines,
            purchase_order_id=purchase_order_id,
            tax_minor=tax_minor,
            due_date=due_date,
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
        )

    def submit_supplier_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self.repository.submit_supplier_invoice(
            invoice_id, expected_version=expected_version, actor_label=actor_label
        )

    def run_three_way_match(self, invoice_id: str, *, actor_label: str = "local-cli") -> ThreeWayMatchResult:
        return self.repository.run_three_way_match(invoice_id, actor_label=actor_label)

    def approve_supplier_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self.repository.approve_supplier_invoice(
            invoice_id, expected_version=expected_version, actor_label=actor_label
        )

    def get_supplier(self, supplier_id: str) -> dict[str, Any]:
        return self.repository.get_supplier(supplier_id)

    def get_purchase_order(self, purchase_order_id: str) -> dict[str, Any]:
        return self.repository.get_purchase_order(purchase_order_id)

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self.repository.get_receipt(receipt_id)

    def get_supplier_invoice(self, invoice_id: str) -> dict[str, Any]:
        return self.repository.get_supplier_invoice(invoice_id)

    def list_suppliers(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        return self.repository.list_suppliers(workspace=workspace, status=status)

    def list_supplier_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        return self.repository.list_supplier_invoices(workspace=workspace, status=status)
