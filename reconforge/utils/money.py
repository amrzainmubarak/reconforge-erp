"""Money utilities."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_money(value: float | int | str | None, places: int = 2) -> float:
    """Round a monetary value using accounting-friendly half-up behavior."""

    if value is None:
        return 0.0
    decimal_value = Decimal(str(value))
    quant = Decimal("1").scaleb(-places)
    return float(decimal_value.quantize(quant, rounding=ROUND_HALF_UP))


def money_difference(left: float | int | None, right: float | int | None) -> float:
    """Return a rounded absolute difference between two amounts."""

    return abs(round_money(left or 0.0) - round_money(right or 0.0))


def within_tolerance(left: float | int | None, right: float | int | None, tolerance: float) -> bool:
    """Return true when two monetary values are within the configured tolerance."""

    return money_difference(left, right) <= tolerance
