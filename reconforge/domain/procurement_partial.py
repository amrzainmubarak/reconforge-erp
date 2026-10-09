"""Exact partial stock procurement over the existing AP, FIFO and GL engines."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from reconforge.domain.inventory_receipt_posting import exact_date, exact_text
from reconforge.domain.payables_quantities import exact_sum, quantity_text
from reconforge.domain.procurement_operations import ProcurementError, ProcurementPreparation, line_total, normalize

MAX_PARTS = 32
MAX_ORDER_LINES = 128
MAX_ENTERPRISE_PARTS = 1024
DOCUMENT_PAGE_SIZE = 25
ORDER_STAGES = ("Draft", "Submitted", "Approved")
RECEIPT_STAGES = ("Prepared", "Reviewed", "Posted")
INVOICE_STAGES = ("Matched", "Approved", "AccrualPrepared", "AccrualReviewed", "Accrued")


class ProcurementPartialError(ProcurementError):
    """Safe exact quantity, authority or optimistic command failure."""


def require_third_poster(preparer_id: str, reviewer_id: str | None, poster_id: str) -> None:
    """Compare canonical retained identities after current human authority checks."""
    actors = (preparer_id, reviewer_id, poster_id)
    if any(not isinstance(identifier, str) or not identifier for identifier in actors) or len(set(actors)) != 3:
        raise ProcurementPartialError(
            "procurement_partial_duties_conflict",
            "Partial receipt and accrual publication require three distinct human identities: preparer, reviewer and poster.",
        )


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


@dataclass(frozen=True, kw_only=True)
class ProcurementOrderLine:
    item_code: str
    quantity: str
    unit_price_minor: int
    location_code: str
    policy_code: str


@dataclass(frozen=True, kw_only=True)
class MultilineProcurementPreparation:
    number: str
    supplier_code: str
    currency_code: str
    posting_date: str
    period_id: str
    journal_code: str
    ap_account_code: str
    cash_account_code: str
    organization_code: str
    entity_code: str
    lines: tuple[ProcurementOrderLine, ...]
    workspace: str = "default"


@dataclass(frozen=True, kw_only=True)
class ProcurementLineQuantity:
    line_id: str
    quantity: str


@dataclass(frozen=True, kw_only=True)
class MultilineInvoicePreparation:
    lines: tuple[ProcurementLineQuantity, ...]
    posting_date: str
    period_id: str
    reason: str


def normalize_multiline(request: MultilineProcurementPreparation) -> tuple[MultilineProcurementPreparation, int]:
    """One purchase document; quantities never combine across different units."""
    from dataclasses import asdict

    if not isinstance(request.lines, tuple) or not 1 <= len(request.lines) <= MAX_ORDER_LINES:
        raise ProcurementPartialError("procurement_partial_lines_invalid", "An order requires one to 128 exact lines.")
    header = asdict(request)
    header.pop("lines")
    normalized: list[ProcurementOrderLine] = []
    total = 0
    for line in request.lines:
        candidate = normalize_order(ProcurementPreparation(**header, **asdict(line)))
        _, amount = line_total(candidate.quantity, candidate.unit_price_minor)
        total += amount
        if total > 9_000_000_000_000_000_000:
            raise ProcurementPartialError("procurement_partial_amount_invalid", "Purchase total exceeds supported exact minor units.")
        normalized.append(ProcurementOrderLine(item_code=candidate.item_code, quantity=candidate.quantity,
            unit_price_minor=candidate.unit_price_minor, location_code=candidate.location_code, policy_code=candidate.policy_code))
    return replace(request, **{key: getattr(candidate, key) for key in header}, lines=tuple(normalized)), total


def normalize_invoice_lines(request: MultilineInvoicePreparation) -> MultilineInvoicePreparation:
    if not isinstance(request.lines, tuple) or not 1 <= len(request.lines) <= MAX_ORDER_LINES:
        raise ProcurementPartialError("procurement_partial_lines_invalid", "An invoice requires one to 128 exact line allocations.")
    identifiers = [exact_text(line.line_id) for line in request.lines]
    if len(set(identifiers)) != len(identifiers):
        raise ProcurementPartialError("procurement_partial_lines_invalid", "Invoice allocations must select each purchase line once.")
    return replace(request, lines=tuple(replace(line, line_id=identifier) for line, identifier in zip(request.lines, identifiers, strict=True)),
        posting_date=exact_date(request.posting_date), period_id=exact_text(request.period_id), reason=exact_text(request.reason, maximum=500))
