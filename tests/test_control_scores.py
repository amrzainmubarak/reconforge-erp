from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from reconforge.domain.control_scores import percentage_from_counts, readiness_percentage


def test_readiness_percentage_is_exact_under_hostile_ambient_context() -> None:
    with localcontext() as context:
        context.prec = 4
        hostile = readiness_percentage(complete=1, total=3)
    normal = readiness_percentage(complete=1, total=3)

    assert hostile == normal == Decimal("33.33")
    assert readiness_percentage(complete=2, total=3) == Decimal("66.67")
    assert readiness_percentage(complete=3, total=3) == Decimal("100.00")
    assert readiness_percentage(complete=0, total=0) == Decimal("0.00")


@pytest.mark.parametrize(
    ("complete", "total"),
    [(-1, 1), (2, 1), (0, -1), (True, 1)],
)
def test_readiness_percentage_rejects_inconsistent_counts(complete: int, total: int) -> None:
    with pytest.raises(ValueError, match="readiness counts"):
        readiness_percentage(complete=complete, total=total)


def test_percentage_from_counts_supports_explicit_empty_policy() -> None:
    assert percentage_from_counts(numerator=0, denominator=0) == Decimal("0.00")
    assert percentage_from_counts(
        numerator=0,
        denominator=0,
        empty_value=Decimal("100.00"),
    ) == Decimal("100.00")
