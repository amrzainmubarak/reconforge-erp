"""Independent rational-arithmetic oracle for Payables quantity conservation."""

from decimal import Decimal, localcontext
from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from reconforge.domain.payables_quantities import exact_sum, quantity_capacity, quantity_text


@given(
    values=st.lists(st.tuples(st.integers(-(10**35), 10**35), st.integers(0, 35)), max_size=20),
    precision=st.integers(1, 28),
)
def test_quantity_sum_and_canonical_text_equal_independent_rational_oracle(
    values: list[tuple[int, int]], precision: int,
) -> None:
    decimals = [Decimal((int(coefficient < 0), tuple(int(char) for char in str(abs(coefficient))), -scale)) for coefficient, scale in values]
    expected = sum((Fraction(value) for value in decimals), Fraction(0))
    with localcontext() as context:
        context.prec = precision
        actual = exact_sum(decimals)
        text = quantity_text(actual)
    assert Fraction(actual) == expected
    assert Fraction(Decimal(text)) == expected


def test_quantity_surplus_on_one_line_cannot_cancel_shortage_on_another() -> None:
    variance, exceeded = quantity_capacity(
        {"line-a": Decimal(3), "line-b": Decimal(1)},
        {"line-a": (Decimal(2), Decimal(2), Decimal(0)), "line-b": (Decimal(2), Decimal(2), Decimal(0))},
    )
    assert variance == 0
    assert exceeded == ("line-a",)
