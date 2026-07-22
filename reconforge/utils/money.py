"""Money utilities."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class InvalidAmountError(ValueError):
    """Raised when a financial value cannot be interpreted safely."""


def parse_amount(value: object) -> Decimal:
    """Parse a finite financial amount without silently substituting zero.

    Comma group separators and conventional accounting parentheses are
    accepted. Missing, boolean, malformed, NaN, and infinite values are
    rejected so callers must make an explicit data-quality decision.
    """

    if value is None or isinstance(value, bool):
        raise InvalidAmountError("financial amount is missing or invalid")
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "nat", "none", "null", "n/a"}:
        raise InvalidAmountError("financial amount is missing or invalid")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    normalized = text.replace(",", "")
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as exc:
        raise InvalidAmountError("financial amount is not numeric") from exc
    if not parsed.is_finite():
        raise InvalidAmountError("financial amount must be finite")
    return -parsed if negative else parsed


def round_money(value: float | int | str | Decimal | None, places: int = 2) -> Decimal:
    """Round a monetary value using accounting-friendly half-up behavior."""

    if value is None:
        return Decimal("0")
    decimal_value = parse_amount(value)
    quant = Decimal("1").scaleb(-places)
    return decimal_value.quantize(quant, rounding=ROUND_HALF_UP)


def money_difference(left: float | int | str | Decimal | None, right: float | int | str | Decimal | None) -> Decimal:
    """Return a rounded absolute difference between two amounts."""

    return abs(round_money(left or 0) - round_money(right or 0))


def within_tolerance(
    left: float | int | str | Decimal | None,
    right: float | int | str | Decimal | None,
    tolerance: float | int | str | Decimal,
) -> bool:
    """Return true when two monetary values are within the configured tolerance."""

    return money_difference(left, right) <= round_money(tolerance)
