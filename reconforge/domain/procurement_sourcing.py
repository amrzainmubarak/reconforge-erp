"""Versioned procurement demand, immutable offers and exact deterministic awards."""
from __future__ import annotations

from dataclasses import dataclass, replace

from reconforge.domain.budget_control import text
from reconforge.domain.inventory_receipt_posting import exact_date, exact_text
from reconforge.domain.procurement_operations import line_total
from reconforge.domain.procurement_partial import (
    MultilineProcurementPreparation,
    ProcurementPartialError,
    normalize_multiline,
)

SCHEMA_VERSION = "procurement-sourcing-v1"
MAX_QUOTES = 32
PERMISSIONS = {
    "read": frozenset({"procurement_sourcing.read", "budget_control.read", "payables.read", "inventory.read", "finance_core.read"}),
    "create": frozenset({"procurement_sourcing.manage"}),
    "open-rfq": frozenset({"procurement_sourcing.approve"}),
    "quote": frozenset({"procurement_sourcing.manage"}),
    "review-selection": frozenset({"procurement_sourcing.approve"}),
    "award": frozenset({"procurement_sourcing.award", "budget_control.manage", "payables.manage"}),
    "cancel": frozenset({"procurement_sourcing.approve"}),
}
STAGES = ("Draft", "OpenRFQ", "SelectionReviewed", "Awarded", "Cancelled")


@dataclass(frozen=True, kw_only=True)
class RequirementReference:
    requirement_id: str
    requirement_digest: str


@dataclass(frozen=True, kw_only=True)
class RequisitionPreparation:
    budget_id: str
    order: MultilineProcurementPreparation
    reason: str
    requirements: tuple[RequirementReference | None, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SupplierQuotationPreparation:
    supplier_code: str
    unit_prices_minor: tuple[int, ...]
    valid_until: str
    reason: str


def normalize_requisition(request: RequisitionPreparation) -> tuple[RequisitionPreparation, int]:
    budget_id, reason = text(request.budget_id, "Budget ID"), text(request.reason, "Reason", 500)
    order, total = normalize_multiline(request.order)
    if not order.number.startswith("SRC5-") or not 5 < len(order.number) <= 30:
        raise ProcurementPartialError("procurement_sourcing_number_invalid", "Requisitions require SRC5- and a bounded nonempty suffix.")
    references = request.requirements or (None,) * len(order.lines)
    if len(references) != len(order.lines):
        raise ProcurementPartialError("procurement_sourcing_requirement_invalid", "Each demand line requires its matching optional manufacturing reference.")
    selected: set[str] = set()
    for reference in references:
        if reference is None:
            continue
        text(reference.requirement_id, "Manufacturing requirement")
        if (reference.requirement_id in selected or len(reference.requirement_digest) != 64
                or any(char not in "0123456789abcdef" for char in reference.requirement_digest)):
            raise ProcurementPartialError("procurement_sourcing_requirement_invalid", "Requirement IDs must be distinct and bind their exact immutable source digest.")
        selected.add(reference.requirement_id)
    return replace(request, budget_id=budget_id, order=order, reason=reason, requirements=references), total


def quotation_order(source: MultilineProcurementPreparation, quote: SupplierQuotationPreparation) -> tuple[MultilineProcurementPreparation, int]:
    if not isinstance(quote.unit_prices_minor, tuple) or len(quote.unit_prices_minor) != len(source.lines):
        raise ProcurementPartialError("procurement_sourcing_quote_invalid", "Quotation prices must match all immutable demanded lines in order.")
    exact_text(quote.reason, maximum=500)
    valid_until = exact_date(quote.valid_until)
    if valid_until < source.posting_date:
        raise ProcurementPartialError("procurement_sourcing_quote_expired", "The retained offer must cover the original purchase business date.")
    for line, price in zip(source.lines, quote.unit_prices_minor, strict=True):
        if type(price) is not int or price < 1:
            raise ProcurementPartialError("procurement_sourcing_quote_invalid", "Quotation prices require exact positive integer minor units.")
        line_total(line.quantity, price)
    order, total = normalize_multiline(replace(source, number="BPC1-" + source.number,
        supplier_code=quote.supplier_code,
        lines=tuple(replace(line, unit_price_minor=price) for line, price in zip(source.lines, quote.unit_prices_minor, strict=True))))
    return order, total


def deterministic_winner(offers: tuple[tuple[str, str, int], ...], ceiling_minor: int) -> str:
    """Exactly one retained quote per supplier; no arrival-time or random tie-break."""
    if not offers or len(offers) > MAX_QUOTES or type(ceiling_minor) is not int or ceiling_minor < 1:
        raise ProcurementPartialError("procurement_sourcing_selection_invalid", "A bounded nonempty exact retained quotation set is required.")
    suppliers: set[str] = set()
    identifiers: set[str] = set()
    for identifier, supplier, total in offers:
        exact_text(identifier)
        exact_text(supplier, maximum=64)
        if identifier in identifiers or supplier in suppliers or type(total) is not int or not 1 <= total <= 9_000_000_000_000_000_000:
            raise ProcurementPartialError("procurement_sourcing_selection_invalid", "Retained quotation membership and supplier identity must be unique and exact.")
        identifiers.add(identifier)
        suppliers.add(supplier)
    winner = min(offers, key=lambda item: (item[2], item[1]))
    if winner[2] > ceiling_minor:
        raise ProcurementPartialError("procurement_sourcing_ceiling_exceeded", "No retained offer meets the original independently approved demand ceiling.")
    return winner[0]

