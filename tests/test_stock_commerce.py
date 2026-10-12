"""Independent commercial money and line contract boundaries."""
import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.stock_commerce import CommercialLine, CommercialOrder


def test_commercial_lines_keep_exact_discounted_aggregate_and_warehouse_identity() -> None:
    order = CommercialOrder("BUSINESS-1", "CUSTOMER", "PO-1", "USD", "2026-10-09", (
        CommercialLine("A", "NORTH", "STOCK", "7", 1251, "Product A", 1000),
        CommercialLine("B", "SOUTH", "STOCK", "3", 2021, "Product B", 250)))
    snapshot = order.payload()
    # Independent integer HALF_UP per-unit calculations, no engine-derived expectation.
    assert snapshot["header"]["total_minor"] == 7 * 1126 + 3 * 1970
    assert [line["warehouse_code"] for line in snapshot["lines"]] == ["NORTH", "SOUTH"]
    assert snapshot["header"]["line_count"] == 2


def test_thousand_distinct_products_have_one_commercial_parent() -> None:
    lines = tuple(CommercialLine(f"SKU-{index}", "NORTH", "STOCK", "2", 1000 + index, "Synthetic") for index in range(1000))
    snapshot = CommercialOrder("DISTRIBUTOR", "CUSTOMER", "PO-1", "USD", "2026-10-09", lines).payload()
    assert snapshot["header"]["total_minor"] == 2 * (1000 * 1000 + 999 * 1000 // 2)


@pytest.mark.parametrize("quantity,price", [("1e3", 100), ("NaN", 100), ("-1", 100), ("2", True), ("1", 9_000_000_000_000_000_001)])
def test_commercial_order_refuses_inexact_inputs(quantity: str, price: int) -> None:
    with pytest.raises(FinancePostingError):
        CommercialOrder("ORDER", "CUSTOMER", "REF", "USD", "2026-10-09",
            (CommercialLine("SKU", "MAIN", "STOCK", quantity, price, "Synthetic"),)).payload()
