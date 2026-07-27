"""Exact domain calculations for control-decision scores."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

READINESS_QUANTUM = Decimal("0.01")
COMPLETE_READINESS = Decimal("100.00")


def percentage_from_counts(
    *,
    numerator: int,
    denominator: int,
    empty_value: Decimal = Decimal("0.00"),
) -> Decimal:
    """Return an exact two-decimal percentage from bounded integer counts."""

    if isinstance(numerator, bool) or isinstance(denominator, bool):
        raise ValueError("percentage counts must be integers")
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        raise ValueError("percentage counts must be integers")
    if denominator < 0 or numerator < 0 or numerator > denominator:
        raise ValueError("percentage counts are inconsistent")
    if not empty_value.is_finite() or empty_value < 0 or empty_value > 100:
        raise ValueError("empty percentage must be finite and between 0 and 100")
    if denominator == 0:
        required_precision = max(28, len(empty_value.as_tuple().digits) + 4)
        with localcontext() as context:
            context.prec = required_precision
            return empty_value.quantize(READINESS_QUANTUM, rounding=ROUND_HALF_UP)

    required_precision = max(28, len(str(numerator)) + len(str(denominator)) + 8)
    with localcontext() as context:
        context.prec = required_precision
        return ((Decimal(numerator) * Decimal(100)) / Decimal(denominator)).quantize(
            READINESS_QUANTUM,
            rounding=ROUND_HALF_UP,
        )


def readiness_percentage(*, complete: int, total: int) -> Decimal:
    """Return an exact two-decimal completion percentage from integer counts."""

    try:
        return percentage_from_counts(numerator=complete, denominator=total)
    except ValueError as exc:
        raise ValueError(str(exc).replace("percentage", "readiness")) from exc
