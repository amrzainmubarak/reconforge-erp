"""Independent integer/Fraction oracle for original whole credits and refunds."""

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.domain.customer_returns import MAX_MINOR, credit_entitlement
from reconforge.domain.finance_posting import FinancePostingError


@given(gross=st.integers(min_value=1, max_value=10**15), cost=st.integers(min_value=1, max_value=10**15),
       part=st.integers(min_value=0, max_value=10000))
def test_whole_credit_conserves_independent_customer_net_and_fifo(gross: int, cost: int, part: int) -> None:
    collected = int(Fraction(gross * part, 10000))
    expected_ar = Fraction(gross) - collected - gross + collected
    expected_liability = Fraction(collected)
    effect = credit_entitlement(gross, collected, cost)
    assert expected_ar == 0
    assert effect == {"credit_minor": gross, "receivable_released_minor": gross - collected,
                      "refund_entitlement_minor": expected_liability, "cogs_restored_minor": cost,
                      "turnover_minor": Fraction(gross) + cost + collected}
    first = collected // 3
    second = collected - first
    assert expected_liability - first - second == 0


@pytest.mark.parametrize("values", [(True, 0, 1), (1, 1.0, 1), (1, -1, 1), (1, 2, 1), (MAX_MINOR, 0, 1)])
def test_credit_never_defaults_or_overflows_financial_values(values: tuple[object, ...]) -> None:
    with pytest.raises(FinancePostingError):
        credit_entitlement(*values)  # type: ignore[arg-type]
