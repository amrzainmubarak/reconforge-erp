"""Backend-neutral governed accounts-receivable application boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


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


class ReceivablesRepositoryProtocol(Protocol):
    """Complete persistence and policy port for governed receivables."""

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
    ) -> dict[str, Any]: ...
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
    ) -> dict[str, Any]: ...
    def submit_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def approve_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        credit_override_reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
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
    ) -> dict[str, Any]: ...
    def allocate_receipt(
        self,
        receipt_id: str,
        *,
        invoice_id: str,
        amount_minor: int,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def get_customer(self, customer_id: str) -> dict[str, Any]: ...
    def get_invoice(self, invoice_id: str) -> dict[str, Any]: ...
    def get_receipt(self, receipt_id: str) -> dict[str, Any]: ...
    def list_customers(self, *, workspace: str = "", status: str = "") -> list[dict[str, Any]]: ...
    def list_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]: ...
    def credit_exposure(self, customer_code: str, *, workspace: str = "default") -> dict[str, Any]: ...
    def aging_report(self, *, workspace: str = "default", as_of_date: str) -> dict[str, Any]: ...


class ReceivablesApplicationService:
    """Coordinate receivable use cases without a database dependency."""

    def __init__(self, repository: ReceivablesRepositoryProtocol) -> None:
        self.repository = repository

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
        return self.repository.upsert_customer(
            customer_code=customer_code,
            name=name,
            currency_code=currency_code,
            credit_limit_minor=credit_limit_minor,
            credit_hold=credit_hold,
            payment_terms_days=payment_terms_days,
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            tax_identifier=tax_identifier,
            status=status,
            actor_label=actor_label,
        )

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
        return self.repository.create_invoice(
            invoice_number=invoice_number,
            customer_code=customer_code,
            invoice_date=invoice_date,
            currency_code=currency_code,
            tax_minor=tax_minor,
            lines=lines,
            due_date=due_date,
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
        )

    def submit_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self.repository.submit_invoice(invoice_id, expected_version=expected_version, actor_label=actor_label)

    def approve_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        credit_override_reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.approve_invoice(
            invoice_id,
            expected_version=expected_version,
            credit_override_reason=credit_override_reason,
            actor_label=actor_label,
        )

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
        return self.repository.post_receipt(
            receipt_number=receipt_number,
            customer_code=customer_code,
            receipt_date=receipt_date,
            currency_code=currency_code,
            amount_minor=amount_minor,
            allocations=allocations,
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
        )

    def allocate_receipt(
        self,
        receipt_id: str,
        *,
        invoice_id: str,
        amount_minor: int,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.allocate_receipt(
            receipt_id,
            invoice_id=invoice_id,
            amount_minor=amount_minor,
            expected_version=expected_version,
            actor_label=actor_label,
        )

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        return self.repository.get_customer(customer_id)

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return self.repository.get_invoice(invoice_id)

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self.repository.get_receipt(receipt_id)

    def list_customers(self, *, workspace: str = "", status: str = "") -> list[dict[str, Any]]:
        return self.repository.list_customers(workspace=workspace, status=status)

    def list_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        return self.repository.list_invoices(workspace=workspace, status=status)

    def credit_exposure(self, customer_code: str, *, workspace: str = "default") -> dict[str, Any]:
        return self.repository.credit_exposure(customer_code, workspace=workspace)

    def aging_report(self, *, workspace: str = "default", as_of_date: str) -> dict[str, Any]:
        return self.repository.aging_report(workspace=workspace, as_of_date=as_of_date)
