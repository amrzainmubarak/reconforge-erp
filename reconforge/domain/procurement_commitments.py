"""Exact merchandise appropriation over the existing purchase and budget engines."""
from __future__ import annotations

from dataclasses import dataclass, replace

from reconforge.domain.budget_control import text
from reconforge.domain.procurement_partial import (
    MultilineProcurementPreparation,
    ProcurementPartialError,
    normalize_multiline,
)

PREFIX = "BPC1-"


@dataclass(frozen=True, kw_only=True)
class BudgetPurchasePreparation:
    budget_id: str
    expected_budget_version: int
    order: MultilineProcurementPreparation
    reason: str


def version(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 9_000_000_000_000_000_000:
        raise ProcurementPartialError("procurement_commitment_version_invalid", "A bounded positive exact version is required.")
    return value


def normalize(request: BudgetPurchasePreparation) -> tuple[BudgetPurchasePreparation, int]:
    text(request.budget_id, "Budget ID")
    text(request.reason, "Reason", 500)
    version(request.expected_budget_version)
    order, total = normalize_multiline(request.order)
    if not order.number.startswith(PREFIX) or len(order.number) <= len(PREFIX):
        raise ProcurementPartialError("procurement_commitment_number_invalid", "Budget-backed purchase numbers require BPC1- and a nonempty business suffix.")
    return replace(request, order=order), total


def conservation(original: int, consumed: int, released: int) -> int:
    if any(type(item) is not int for item in (original, consumed, released)) or original < 1 or min(consumed, released) < 0:
        raise ProcurementPartialError("procurement_commitment_evidence_invalid", "Commitment amounts must be exact nonnegative integers.")
    remaining = original - consumed - released
    if remaining < 0:
        raise ProcurementPartialError("procurement_commitment_capacity_conflict", "Consumed and released value exceeds the original native purchase obligation.")
    return remaining
