"""Independent exact multiline cost and immutable allocation admission."""
from dataclasses import replace
from decimal import localcontext

import pytest

from reconforge.domain.procurement_partial import (
    MultilineInvoicePreparation,
    MultilineProcurementPreparation,
    ProcurementLineQuantity,
    ProcurementOrderLine,
    ProcurementPartialError,
    normalize_invoice_lines,
    normalize_multiline,
)


def enterprise_request(number: str = "MULTI-1") -> MultilineProcurementPreparation:
    return MultilineProcurementPreparation(number=number, supplier_code="SUPPLIER", currency_code="USD",
        posting_date="2026-10-03", period_id="period", journal_code="STOCK", ap_account_code="AP", cash_account_code="CASH",
        organization_code="ORG", entity_code="ENTITY", workspace="work", lines=(
            ProcurementOrderLine(item_code="ITEM", quantity="10", unit_price_minor=1200, location_code="MAIN/STOCK", policy_code="FIFO"),
            ProcurementOrderLine(item_code="WEIGHT", quantity="2.50", unit_price_minor=2000, location_code="NORTH/STOCK", policy_code="FIFO")))


def test_heterogeneous_units_sum_money_only_and_ignore_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 1
        request, total = normalize_multiline(enterprise_request())
    assert total == 17000
    assert [(line.item_code, line.quantity, line.location_code) for line in request.lines] == [
        ("ITEM", "10", "MAIN/STOCK"), ("WEIGHT", "2.50", "NORTH/STOCK")]
    assert not hasattr(request, "quantity")


@pytest.mark.parametrize("lines", [(), enterprise_request().lines * 65])
def test_multiline_order_requires_bounded_actual_lines(lines: tuple[ProcurementOrderLine, ...]) -> None:
    with pytest.raises(ProcurementPartialError, match="128"):
        normalize_multiline(replace(enterprise_request(), lines=lines))


def test_individually_valid_lines_cannot_overflow_document_minor_total() -> None:
    line = replace(enterprise_request().lines[0], quantity="1", unit_price_minor=5_000_000_000_000_000_000)
    with pytest.raises(ProcurementPartialError, match="total"):
        normalize_multiline(replace(enterprise_request(), lines=(line, line)))


def test_invoice_rejects_duplicate_line_even_if_quantities_differ() -> None:
    request = MultilineInvoicePreparation(posting_date="2026-10-04", period_id="period", reason="Exact matching",
        lines=(ProcurementLineQuantity(line_id="line-1", quantity="1"), ProcurementLineQuantity(line_id="line-1", quantity="2")))
    with pytest.raises(ProcurementPartialError, match="once"):
        normalize_invoice_lines(request)


def test_integer_minor_cost_rejects_fractional_line_total_before_native_write() -> None:
    line = replace(enterprise_request().lines[0], quantity="0.000001", unit_price_minor=1200)
    with pytest.raises(ProcurementPartialError.__bases__[0], match="exact supported"):
        normalize_multiline(replace(enterprise_request(), lines=(line,)))
