from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from reconforge.application.payables import (
    PayablesApplicationService,
    PayablesRepositoryProtocol,
    PurchaseOrderLineInput,
    SupplierInvoiceLineInput,
    ThreeWayMatchResult,
)


class _RecordingPayablesRepository:
    def __init__(self) -> None:
        self.operation = ""
        self.arguments: dict[str, object] = {}

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
        self.operation = "create_supplier_invoice"
        self.arguments = {
            "invoice_number": invoice_number,
            "supplier_code": supplier_code,
            "invoice_date": invoice_date,
            "currency_code": currency_code,
            "total_minor": total_minor,
            "lines": lines,
            "purchase_order_id": purchase_order_id,
            "tax_minor": tax_minor,
            "due_date": due_date,
            "workspace": workspace,
            "organization_code": organization_code,
            "entity_code": entity_code,
            "idempotency_key": idempotency_key,
            "actor_label": actor_label,
        }
        return {"id": "invoice-1", "total_minor": total_minor, "lines": list(lines)}

    def approve_supplier_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        self.operation = "approve_supplier_invoice"
        self.arguments = {
            "invoice_id": invoice_id,
            "expected_version": expected_version,
            "actor_label": actor_label,
        }
        return {"id": invoice_id, "status": "Approved", "row_version": expected_version + 1}

    def run_three_way_match(self, invoice_id: str, *, actor_label: str = "local-cli") -> ThreeWayMatchResult:
        self.operation = "run_three_way_match"
        self.arguments = {"invoice_id": invoice_id, "actor_label": actor_label}
        return ThreeWayMatchResult("match-1", invoice_id, "po-1", "Matched", "0", 0, 0, "Within policy.")


def _service(repository: _RecordingPayablesRepository) -> PayablesApplicationService:
    return PayablesApplicationService(cast(PayablesRepositoryProtocol, repository))


def test_payables_application_preserves_minor_units_exact_quantity_and_scope() -> None:
    repository = _RecordingPayablesRepository()
    service = _service(repository)
    lines = (
        SupplierInvoiceLineInput(
            purchase_order_line_id="po-line-1",
            invoiced_quantity="999999999999.123456",
            unit_price_minor=9_999_999_999_999,
            line_total_minor=8_888_888_888_888,
            tax_minor=777_777_777_777,
        ),
    )

    result = service.create_supplier_invoice(
        invoice_number="SUP/2026/PORT",
        supplier_code="SUP-1",
        invoice_date="2026-07-28",
        currency_code="KWD",
        total_minor=9_666_666_666_665,
        lines=lines,
        purchase_order_id="po-1",
        tax_minor=777_777_777_777,
        due_date="2026-08-28",
        workspace="regulated",
        organization_code="ORG",
        entity_code="ENTITY",
        idempotency_key="invoice-port-1",
        actor_label="maker@example.test",
    )

    assert repository.operation == "create_supplier_invoice"
    assert repository.arguments["lines"] is lines
    assert result["total_minor"] == 9_666_666_666_665
    assert result["lines"][0].invoiced_quantity == "999999999999.123456"
    assert repository.arguments["workspace"] == "regulated"
    assert repository.arguments["actor_label"] == "maker@example.test"


def test_payables_application_delegates_approval_version_and_deterministic_match() -> None:
    repository = _RecordingPayablesRepository()
    service = _service(repository)

    approved = service.approve_supplier_invoice("invoice-1", expected_version=7, actor_label="checker@example.test")
    assert approved == {"id": "invoice-1", "status": "Approved", "row_version": 8}
    assert repository.arguments == {
        "invoice_id": "invoice-1",
        "expected_version": 7,
        "actor_label": "checker@example.test",
    }

    matched = service.run_three_way_match("invoice-1", actor_label="matcher")
    assert matched == ThreeWayMatchResult("match-1", "invoice-1", "po-1", "Matched", "0", 0, 0, "Within policy.")


def test_payables_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    source_path = Path("reconforge/application/payables.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)


def test_payables_public_line_types_retain_exact_minor_unit_contract() -> None:
    line = PurchaseOrderLineInput("ITEM-1", "0.000001", 123_456_789, tax_minor=987_654)
    assert line.ordered_quantity == "0.000001"
    assert line.unit_price_minor == 123_456_789
    assert line.tax_minor == 987_654
