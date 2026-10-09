"""Independent exact allocation oracle and paid charge admission boundaries."""
from fractions import Fraction
from itertools import permutations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.domain.landed_cost import allocate_minor
from reconforge.domain.procurement_partial import ProcurementPartialError


def oracle(amount: int, weights: tuple[tuple[str, int], ...]) -> dict[str, int]:
    shares = {key: Fraction(amount * weight, sum(value for _, value in weights)) for key, weight in weights}
    result = {key: value.numerator // value.denominator for key, value in shares.items()}
    ordered = sorted(shares, key=lambda key: (-(shares[key] - result[key]), key))
    for key in ordered[:amount - sum(result.values())]:
        result[key] += 1
    return result


@given(st.integers(min_value=0, max_value=9_000_000_000_000_000_000),
       st.lists(st.integers(min_value=1, max_value=9_000_000_000_000_000_000), min_size=1, max_size=128))
def test_allocated_money_matches_independent_rational_oracle(amount: int, values: list[int]) -> None:
    weights = tuple((f"SOURCE-{index:03}", value) for index, value in enumerate(values))
    actual = allocate_minor(amount, weights)
    assert actual == oracle(amount, weights)
    assert sum(actual.values()) == amount
    assert allocate_minor(amount, tuple(reversed(weights))) == actual


def test_tiny_fee_ties_and_zero_shares_do_not_depend_on_input_order() -> None:
    for order in permutations((("C", 100), ("A", 100), ("B", 100))):
        assert allocate_minor(1, order) == {"A": 1, "B": 0, "C": 0}


@pytest.mark.parametrize("amount,weights", [(True, (("A", 1),)), (1.0, (("A", 1),)), (-1, (("A", 1),)),
    (1, (("A", 0),)), (1, (("A", 1), ("A", 2))), (1, ())])
def test_invalid_exact_financial_values_are_rejected(amount: int, weights: tuple[tuple[str, int], ...]) -> None:
    with pytest.raises(ProcurementPartialError):
        allocate_minor(amount, weights)
