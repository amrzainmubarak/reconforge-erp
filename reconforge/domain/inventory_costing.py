"""FIFO's existing HALF_EVEN minor-unit allocation using exact integer ratios."""

from __future__ import annotations


def allocate_fifo_value(remaining_value: int, remaining_quantity: int, consumed_quantity: int) -> int:
    """Allocate partial cost, retaining all residual minor units for final issue.

    A partial issue must leave positive cost for its positive remaining quantity.
    No Decimal division or ambient precision/trap setting participates.
    """

    if any(type(value) is not int or value <= 0 for value in (remaining_value, remaining_quantity, consumed_quantity)):
        raise ValueError("FIFO values and quantities must be positive integers.")
    if consumed_quantity > remaining_quantity:
        raise ValueError("FIFO consumption cannot exceed the remaining quantity.")
    if consumed_quantity == remaining_quantity:
        return remaining_value
    quotient, remainder = divmod(remaining_value * consumed_quantity, remaining_quantity)
    if remainder * 2 > remaining_quantity or (remainder * 2 == remaining_quantity and quotient % 2):
        quotient += 1
    if quotient <= 0 or quotient >= remaining_value:
        raise ValueError(
            "A partial FIFO issue cannot be represented exactly enough in currency minor units; "
            "consume the layer fully or use a more granular receipt quantity."
        )
    return quotient
