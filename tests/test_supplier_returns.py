"""Independent exact supplier-credit and paid original-charge conservation."""
from decimal import Decimal, localcontext

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.supplier_returns import SupplierReturnPreparation, return_values


def test_original_cost_and_supplier_credit_conserve_under_small_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 2
        result = return_values(12000, 12706)
    assert result == {"credit_minor": 12000, "inventory_removed_minor": 12706, "charge_expense_minor": 706, "amount_minor": 25412}
    assert result["credit_minor"] + result["charge_expense_minor"] == result["inventory_removed_minor"]


@pytest.mark.parametrize("merchandise,capitalized", [(True, 1), (Decimal("1"), 1), (1, 0), (2, 1), (1, 4_500_000_000_000_000_001)])
def test_original_money_refuses_lossy_or_outside_native_boundaries(merchandise: object, capitalized: int) -> None:
    with pytest.raises(FinancePostingError):
        return_values(merchandise, capitalized)


def test_bounded_source_number_and_business_date_are_explicit() -> None:
    request = SupplierReturnPreparation(order_id="order", receipt_id="receipt", invoice_id="invoice", number="SR1-SOURCE", period_id="period",
        posting_date="2026-10-05", expense_account_code="EXPENSE", reason="Original unused quantity")
    assert request.payload()["posting_date"] == "2026-10-05"
    with pytest.raises(FinancePostingError):
        SupplierReturnPreparation(**{**request.payload(), "number": "NO-SOURCE"}).payload()
