"""Pre-publication paid landed costs, allocated with exact integer arithmetic."""
from __future__ import annotations

from dataclasses import dataclass, replace

from reconforge.domain.inventory_receipt_posting import exact_date, exact_text
from reconforge.domain.procurement_partial import ProcurementLineQuantity, ProcurementPartialError

MAX_MINOR = 9_000_000_000_000_000_000


@dataclass(frozen=True, kw_only=True)
class LandedCostPreparation:
    number: str
    order_id: str
    expected_version: int
    lines: tuple[ProcurementLineQuantity, ...]
    freight_minor: int
    duty_minor: int
    posting_date: str
    period_id: str
    reason: str


def normalize(request: LandedCostPreparation) -> LandedCostPreparation:
    if type(request.expected_version) is not int or request.expected_version < 1:
        raise ProcurementPartialError("landed_cost_version_invalid", "A positive source version is required.")
    if (not isinstance(request.lines, tuple) or not 1 <= len(request.lines) <= 128
            or len({line.line_id for line in request.lines}) != len(request.lines)):
        raise ProcurementPartialError("landed_cost_lines_invalid", "Select one to 128 distinct actual purchase lines.")
    if any(type(amount) is not int or not 0 <= amount <= MAX_MINOR for amount in (request.freight_minor, request.duty_minor)):
        raise ProcurementPartialError("landed_cost_amount_invalid", "Freight and duties require nonnegative exact minor units.")
    if not 1 <= request.freight_minor + request.duty_minor <= MAX_MINOR:
        raise ProcurementPartialError("landed_cost_amount_invalid", "A positive bounded total paid landed cost is required.")
    return replace(request, number=exact_text(request.number, maximum=40), order_id=exact_text(request.order_id),
                   posting_date=exact_date(request.posting_date), period_id=exact_text(request.period_id),
                   reason=exact_text(request.reason, maximum=500))


def allocate_minor(amount: int, weights: tuple[tuple[str, int], ...]) -> dict[str, int]:
    """Hamilton allocation; stable source IDs break ties, independent of row order.

    Each positive merchandise value is a weight. Zero allocated charges are valid
    for inexpensive lines. No units of measure are added together.
    """
    if type(amount) is not int or not 0 <= amount <= MAX_MINOR or not 1 <= len(weights) <= 128:
        raise ProcurementPartialError("landed_cost_allocation_invalid", "Exact bounded amount and merchandise weights are required.")
    if (len({identifier for identifier, _ in weights}) != len(weights)
            or any(not isinstance(identifier, str) or not identifier or type(weight) is not int or not 1 <= weight <= MAX_MINOR
                   for identifier, weight in weights)):
        raise ProcurementPartialError("landed_cost_allocation_invalid", "Distinct source IDs and positive exact merchandise values are required.")
    denominator = sum(weight for _, weight in weights)
    result = {identifier: amount * weight // denominator for identifier, weight in weights}
    residual = amount - sum(result.values())
    ranked = sorted(weights, key=lambda item: (-(amount * item[1] % denominator), item[0]))
    for identifier, _ in ranked[:residual]:
        result[identifier] += 1
    return result
