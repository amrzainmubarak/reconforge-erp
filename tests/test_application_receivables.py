from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from reconforge.application.receivables import (
    ReceiptAllocationInput,
    ReceivableInvoiceLineInput,
    ReceivablesApplicationService,
    ReceivablesRepositoryProtocol,
)


class _RecordingReceivablesRepository:
    def __init__(self) -> None:
        self.operation = ""
        self.arguments: dict[str, object] = {}

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
        self.operation = "post_receipt"
        self.arguments = {
            "receipt_number": receipt_number,
            "customer_code": customer_code,
            "receipt_date": receipt_date,
            "currency_code": currency_code,
            "amount_minor": amount_minor,
            "allocations": allocations,
            "workspace": workspace,
            "organization_code": organization_code,
            "entity_code": entity_code,
            "idempotency_key": idempotency_key,
            "actor_label": actor_label,
        }
        return {"id": "receipt-1", "amount_minor": amount_minor, "allocations": list(allocations)}

    def approve_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        credit_override_reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self.operation = "approve_invoice"
        self.arguments = {
            "invoice_id": invoice_id,
            "expected_version": expected_version,
            "credit_override_reason": credit_override_reason,
            "actor_label": actor_label,
        }
        return {"id": invoice_id, "status": "Approved", "row_version": expected_version + 1}

    def aging_report(self, *, workspace: str = "default", as_of_date: str) -> dict[str, Any]:
        self.operation = "aging_report"
        self.arguments = {"workspace": workspace, "as_of_date": as_of_date}
        return {"workspace": workspace, "as_of_date": as_of_date, "total_outstanding_minor": 123}


def _service(repository: _RecordingReceivablesRepository) -> ReceivablesApplicationService:
    return ReceivablesApplicationService(cast(ReceivablesRepositoryProtocol, repository))


def test_receivables_application_preserves_minor_units_allocations_and_scope() -> None:
    repository = _RecordingReceivablesRepository()
    service = _service(repository)
    allocations = (ReceiptAllocationInput("invoice-1", 8_888_888_888_888),)

    result = service.post_receipt(
        receipt_number="RCPT/2026/PORT",
        customer_code="CUS-1",
        receipt_date="2026-07-28",
        currency_code="KWD",
        amount_minor=9_999_999_999_999,
        allocations=allocations,
        workspace="regulated",
        organization_code="ORG",
        entity_code="ENTITY",
        idempotency_key="receipt-port-1",
        actor_label="cashier@example.test",
    )

    assert repository.operation == "post_receipt"
    assert repository.arguments["allocations"] is allocations
    assert result["amount_minor"] == 9_999_999_999_999
    assert result["allocations"][0].amount_minor == 8_888_888_888_888
    assert repository.arguments["workspace"] == "regulated"
    assert repository.arguments["actor_label"] == "cashier@example.test"


def test_receivables_application_delegates_credit_override_version_and_aging_date() -> None:
    repository = _RecordingReceivablesRepository()
    service = _service(repository)

    approved = service.approve_invoice(
        "invoice-1",
        expected_version=4,
        credit_override_reason="Documented committee approval",
        actor_label="checker@example.test",
    )
    assert approved["row_version"] == 5
    assert repository.arguments == {
        "invoice_id": "invoice-1",
        "expected_version": 4,
        "credit_override_reason": "Documented committee approval",
        "actor_label": "checker@example.test",
    }

    report = service.aging_report(workspace="regulated", as_of_date="2026-07-31")
    assert report["total_outstanding_minor"] == 123
    assert repository.arguments == {"workspace": "regulated", "as_of_date": "2026-07-31"}


def test_receivables_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    source_path = Path("reconforge/application/receivables.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)


def test_receivable_invoice_line_retains_exact_quantity_and_minor_units() -> None:
    line = ReceivableInvoiceLineInput("Exact service", "999999999999.123456", 123_456_789, 987_654_321, 11_111)
    assert line.quantity == "999999999999.123456"
    assert line.unit_price_minor == 123_456_789
    assert line.line_total_minor == 987_654_321
