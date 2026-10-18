"""Shared strict amount validation for connector response models."""

from __future__ import annotations

from reconforge.io.writers import canonical_decimal_text
from reconforge.utils.money import InvalidAmountError, parse_exact_amount

_NON_FINITE_TEXT = frozenset(
    {
        "nan",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+infinity",
        "-infinity",
    }
)


def canonical_connector_amount(
    value: object,
    *,
    invalid_message: str = "amount must be exact Decimal text",
    nonfinite_message: str = "amount must be finite",
) -> str:
    """Return one finite canonical amount string or fail closed.

    Connector response schemas use this boundary before computing response
    digests.  The shared parser rejects binary floats and scientific notation,
    while preserving the connector's existing error vocabulary through the
    explicit messages.
    """

    try:
        parsed = parse_exact_amount(value)
    except InvalidAmountError as exc:
        if str(value).strip().casefold() in _NON_FINITE_TEXT:
            raise ValueError(nonfinite_message) from exc
        raise ValueError(invalid_message) from exc
    return canonical_decimal_text(parsed)


__all__ = ["canonical_connector_amount"]
