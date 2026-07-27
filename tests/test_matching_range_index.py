from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from reconforge.platform.common import PlatformError
from reconforge.platform.matching import _AmountRangePartition, _decimal_range_bounds


class _CountingDecimalSequence(Sequence[Decimal]):
    def __init__(self, length: int) -> None:
        self.length = length
        self.lookups = 0

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, index: int | slice) -> Decimal:
        if isinstance(index, slice):
            raise AssertionError("binary-search boundary lookup must not slice the amount index")
        self.lookups += 1
        if index < 0:
            index += self.length
        if index < 0 or index >= self.length:
            raise IndexError(index)
        return Decimal(index)


def _candidate(index: int, amount: str):
    value = Decimal(amount)
    return (index, f"R-{index}", {"id": f"R-{index}", "amount": amount}, value, "USD", 2)


def test_decimal_range_bounds_use_logarithmic_lookups_not_bucket_scan() -> None:
    amounts = _CountingDecimalSequence(1_000_000_000)

    start, end = _decimal_range_bounds(amounts, Decimal("499999999"), Decimal("500000001"))

    assert (start, end) == (499_999_999, 500_000_002)
    assert amounts.lookups <= 64


def test_amount_partition_includes_exact_decimal_boundaries_and_duplicates() -> None:
    candidates = (
        _candidate(1, "99.99"),
        _candidate(2, "100.00"),
        _candidate(3, "100.00"),
        _candidate(4, "100.01"),
        _candidate(5, "100.0101"),
    )
    partition = _AmountRangePartition(
        amounts=tuple(candidate[3] for candidate in candidates),
        candidates=candidates,
    )

    selected = partition.between(Decimal("99.99"), Decimal("100.01"))

    assert [candidate[1] for candidate in selected] == ["R-1", "R-2", "R-3", "R-4"]


def test_amount_partition_rejects_invalid_order_and_bounds() -> None:
    with pytest.raises(PlatformError, match="index is invalid"):
        _AmountRangePartition(
            amounts=(Decimal("2"), Decimal("1")),
            candidates=(_candidate(1, "2"), _candidate(2, "1")),
        )
    partition = _AmountRangePartition(
        amounts=(Decimal("1"),),
        candidates=(_candidate(1, "1"),),
    )
    with pytest.raises(PlatformError, match="bounds"):
        partition.between(Decimal("2"), Decimal("1"))
