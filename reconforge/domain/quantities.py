"""Exact quantities and bounded stock ingress, independent of Decimal context.

Invoice quantity times integer minor-unit price uses HALF_UP, as before. This
does not select or reinterpret a currency's monetary rounding policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_DECIMAL_TEXT = re.compile(r"[0-9]+(?:\.[0-9]+)?", re.ASCII)
MAX_QUANTITY_TEXT_LENGTH = 80
# Match structured-document-ingress-v1's scalar ceiling without importing I/O
# policy into the domain. Apply before expanding a compact Decimal exponent.
MAX_QUANTITY_FIXED_CHARACTERS = 1_000_000


def _decimal_quantity(value: Decimal) -> None:
    if type(value) is not Decimal or not value.is_finite() or value.is_signed() or value.is_zero():
        raise ValueError("Quantity must be finite and positive.")
    fractional_digits = max(-int(value.as_tuple().exponent), 0)
    fixed_characters = max(value.adjusted() + 1, 1) + fractional_digits + int(fractional_digits > 0)
    if fixed_characters > MAX_QUANTITY_FIXED_CHARACTERS:
        raise ValueError("Quantity fixed-point expansion exceeds the supported scalar limit.")


def quantity_decimal_text(value: Decimal) -> str:
    """Canonicalize a parsed positive quantity within the shared scalar ceiling.

    Compatibility adapters own their existing lexical/length policy. In
    particular, local AR historically accepts quantities longer than 80 digits.
    Formatting an exact Decimal does not apply its caller's arithmetic context.
    """

    _decimal_quantity(value)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def quantity_product_minor(value: Decimal, unit_price_minor: int) -> int:
    """Preserve AR's HALF_UP product within the explicit expansion resource bound."""

    _decimal_quantity(value)
    if type(unit_price_minor) is not int or unit_price_minor < 0:
        raise ValueError("Minor-unit price must be a nonnegative integer.")
    numerator, denominator = value.as_integer_ratio()
    quotient, remainder = divmod(numerator * unit_price_minor, denominator)
    return quotient + int(remainder * 2 >= denominator)


def _scale(value: int) -> None:
    if type(value) is not int or not 0 <= value <= MAX_QUANTITY_TEXT_LENGTH:
        raise ValueError("Unsupported decimal scale.")


def scaled_integer_text(value: int, scale: int) -> str:
    """Serialize signed integer units with exactly ``scale`` fractional digits."""

    _scale(scale)
    if type(value) is not int:
        raise ValueError("Scaled value must be an integer.")
    sign = "-" if value < 0 else ""
    digits = str(abs(value)).rjust(scale + 1, "0")
    return sign + (digits[:-scale] + "." + digits[-scale:] if scale else digits)


@dataclass(frozen=True)
class ExactQuantity:
    coefficient: int
    scale: int

    def __post_init__(self) -> None:
        _scale(self.scale)
        if type(self.coefficient) is not int or not 0 <= self.coefficient < 10**MAX_QUANTITY_TEXT_LENGTH:
            raise ValueError("Quantity coefficient is outside the supported range.")

    @property
    def text(self) -> str:
        text = scaled_integer_text(self.coefficient, self.scale)
        return text.rstrip("0").rstrip(".") if "." in text else text

    def scaled(self, scale: int) -> int:
        """Convert exactly, refusing any nonzero digits beyond the given scale."""

        _scale(scale)
        if scale >= self.scale:
            return self.coefficient * 10 ** (scale - self.scale)
        result, remainder = divmod(self.coefficient, 10 ** (self.scale - scale))
        if remainder:
            raise ValueError("Quantity exceeds configured decimal precision.")
        return result

def parse_quantity(
    value: object, *, max_length: int = MAX_QUANTITY_TEXT_LENGTH, allow_zero: bool = False
) -> ExactQuantity:
    """Accept bounded unsigned decimal text, integers, or finite Decimal values.

    Scientific notation in text, binary floats, booleans, custom coercions and
    signed quantities are rejected. A Decimal's coefficient/exponent is already
    exact; check its fixed-point size before formatting to prevent large expansion.
    """

    if type(max_length) is not int or not 1 <= max_length <= MAX_QUANTITY_TEXT_LENGTH:
        raise ValueError("Unsupported quantity text limit.")
    if type(value) is Decimal:
        if not value.is_finite() or value.is_signed():
            raise ValueError("Quantity must be finite and nonnegative.")
        exponent = int(value.as_tuple().exponent)
        fixed_length = max(len(value.as_tuple().digits) + exponent, 1)
        if exponent < 0:
            fixed_length += 1 - exponent
        if fixed_length > max_length:
            raise ValueError("Quantity exceeds the supported text limit.")
        raw = format(value, "f")
    elif type(value) is int:
        if value < 0 or value >= 10**max_length:
            raise ValueError("Quantity exceeds the supported nonnegative range.")
        raw = str(value)
    elif type(value) is str:
        raw = value.strip()
    else:
        raise ValueError("Quantity must be an exact decimal string or integer.")
    if len(raw) > max_length or not _DECIMAL_TEXT.fullmatch(raw):
        raise ValueError("Quantity must be bounded unsigned decimal text without an exponent.")
    whole, _, fractional = raw.partition(".")
    fractional = fractional.rstrip("0")
    coefficient = int(whole + fractional)
    if coefficient == 0 and not allow_zero:
        raise ValueError("Quantity must be positive.")
    return ExactQuantity(coefficient, len(fractional))
