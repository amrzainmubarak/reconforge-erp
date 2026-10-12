"""Exact arithmetic for receipt and invoice quantity conservation.

These operations do not inherit Decimal precision from a request or worker.
The repositories own locking; only Approved/Paid invoices consume receipts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, localcontext


def quantity_text(value: Decimal) -> str:
    """Canonicalize finite decimal text without normalize() rounding its digits."""

    if not value.is_finite():
        raise ValueError("Quantity must be finite.")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    """Sum decimal coefficients exactly, including carry and scale alignment."""

    total = Decimal(0)
    for value in values:
        if not value.is_finite():
            raise ValueError("Quantity must be finite.")
        exponent = min(int(total.as_tuple().exponent), int(value.as_tuple().exponent))
        with localcontext() as context:
            context.prec = max(28, max(total.adjusted(), value.adjusted()) - exponent + 3)
            total += value
    return total


def exact_product(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
        return left * right


def rounded_minor(value: Decimal) -> int:
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + 2, value.adjusted() + 3)
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def quantity_capacity(
    proposed: Mapping[str, Decimal],
    available: Mapping[str, tuple[Decimal, Decimal, Decimal]],
) -> tuple[Decimal, tuple[str, ...]]:
    """Return signed proposed-minus-remaining quantity and per-line overages.

    Each availability tuple is (ordered, posted received, Approved/Paid used).
    Negative variance is legitimate partial invoicing; one line's spare
    quantity can never offset another line's shortage.
    """

    variances = []
    exceeded = []
    for line_id in sorted(proposed):
        ordered, received, consumed = available[line_id]
        variance = exact_sum((proposed[line_id], consumed, min(ordered, received).copy_negate()))
        variances.append(variance)
        if variance > 0:
            exceeded.append(line_id)
    return exact_sum(variances), tuple(exceeded)
