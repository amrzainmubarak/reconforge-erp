"""Exact partial stock procurement over the existing AP, FIFO and GL engines."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from reconforge.domain.inventory_receipt_posting import exact_date, exact_text
from reconforge.domain.payables_quantities import exact_sum, quantity_text
from reconforge.domain.procurement_operations import ProcurementError, ProcurementPreparation, line_total, normalize

MAX_PARTS = 32
ORDER_STAGES = ("Draft", "Submitted", "Approved")
RECEIPT_STAGES = ("Prepared", "Reviewed", "Posted")
INVOICE_STAGES = ("Matched", "Approved", "AccrualPrepared", "AccrualReviewed", "Accrued")


class ProcurementPartialError(ProcurementError):
    """Safe exact quantity, authority or optimistic command failure."""


@dataclass(frozen=True, kw_only=True)
class PartialQuantityPreparation:
    quantity: str
    posting_date: str
    period_id: str
    reason: str


def normalize_order(request: ProcurementPreparation) -> ProcurementPreparation:
    request = normalize(request)
    if len(request.number) > 40 or len(request.quantity) > 64:
        raise ProcurementPartialError("procurement_partial_input_invalid", "Partial order number or quantity is too long.")
    return request


def normalize_part(request: PartialQuantityPreparation, unit_price_minor: int) -> tuple[PartialQuantityPreparation, int]:
    if not isinstance(request.quantity, str) or len(request.quantity) > 64:
        raise ProcurementPartialError("procurement_partial_quantity_invalid", "An exact bounded decimal quantity is required.")
    quantity, amount = line_total(request.quantity, unit_price_minor)
    return replace(request, quantity=quantity_text(Decimal(quantity)), posting_date=exact_date(request.posting_date),
                   period_id=exact_text(request.period_id), reason=exact_text(request.reason, maximum=500)), amount


def reserve_quantity(proposed: str, capacity: str, reserved: tuple[str, ...]) -> str:
    """Conserve quantity without relying on the ambient Decimal precision."""
    remainder = exact_sum((Decimal(capacity), *(Decimal(item).copy_negate() for item in reserved)))
    if Decimal(proposed) > remainder:
        raise ProcurementPartialError("procurement_partial_capacity_conflict", "Quantity exceeds currently available unreserved capacity.")
    return quantity_text(exact_sum((remainder, Decimal(proposed).copy_negate())))
