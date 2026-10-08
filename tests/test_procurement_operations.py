"""Financial boundaries of exact stock procurement command inputs."""
import pytest

from reconforge.domain.procurement_operations import ProcurementError, line_total


@pytest.mark.parametrize(("quantity", "price", "expected"), [("10", 1200, 12000), ("0.5", 1200, 600), ("1.25", 400, 500), ("9000000000000000000", 1, 9000000000000000000)])
def test_exact_stock_cost_respects_fractional_quantity_and_large_boundary(quantity: str, price: int, expected: int) -> None:
    assert line_total(quantity, price)[1] == expected


@pytest.mark.parametrize(("quantity", "price"), [("NaN", 10), ("Infinity", 10), ("0", 10), ("-1", 10), ("0.333", 1), ("9000000000000000001", 1), ("1", True), ("1", 0)])
def test_invalid_or_fractional_minor_cost_never_rounds_to_a_financial_value(quantity: str, price: int) -> None:
    with pytest.raises(ProcurementError):
        line_total(quantity, price)
