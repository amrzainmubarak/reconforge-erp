"""Exact commercial and native FIFO interpretation for product sales."""

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.stock_sales import StockOrder, freeze_fifo, require_stock_posting_duties, stock_code


def test_stock_discount_and_fractional_quantity_reproduce_exact_minor_units() -> None:
    source = StockOrder("so-1", "customer", "PO-1", "item", "main", "stock", "2.5", 1001,
                        "USD", "2026-10-09", "Physical goods", 500).payload()
    assert source["number"] == "SO-1"
    assert source["net_unit_price_minor"] == 951
    assert source["total_minor"] == 2378
    assert source["tax_minor"] == 0


def test_fifo_uses_existing_half_even_and_preserves_selected_residuals() -> None:
    allocation, total = freeze_fifo([
        {"id": "first", "row_version": 1, "remaining_quantity_scaled": 3, "remaining_value_minor": 1001},
        {"id": "second", "row_version": 4, "remaining_quantity_scaled": 7, "remaining_value_minor": 2333},
    ], 5)
    assert [(row["cost_layer_id"], row["quantity_scaled"], row["value_minor"]) for row in allocation] == [
        ("first", 3, 1001), ("second", 2, 667)]
    assert total == 1668
    assert allocation[1]["remaining_quantity_scaled"] == 7
    assert allocation[1]["row_version"] == 4


def test_unvalued_shortfall_and_unrepresentable_fraction_fail_closed() -> None:
    with pytest.raises(FinancePostingError, match="Complete valued FIFO"):
        freeze_fifo([], 1)
    with pytest.raises((FinancePostingError, ValueError)):
        freeze_fifo([{"id": "small", "row_version": 1, "remaining_quantity_scaled": 100,
                      "remaining_value_minor": 1}], 1)


def test_retained_native_number_replays_without_case_or_length_changes() -> None:
    assert stock_code("sale-1", "number") == "SALE-1"
    for invalid in ("ß" * 64, "name with spaces", "a" * 65):
        with pytest.raises(FinancePostingError):
            stock_code(invalid, "number")


def test_each_financial_post_requires_three_distinct_retained_humans() -> None:
    require_stock_posting_duties("poster", "maker", "checker")
    for actor, preparer, reviewer in (("maker", "maker", "checker"), ("checker", "maker", "checker"),
                                      ("poster", "maker", "maker"), ("poster", "maker", None), ("", "maker", "checker")):
        with pytest.raises(FinancePostingError) as refusal:
            require_stock_posting_duties(actor, preparer, reviewer)
        assert refusal.value.code == "stock_sales_sod_denied"
