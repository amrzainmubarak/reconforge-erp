"""Bounded FIFO carry-forward allocation with visible residuals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

CarryForwardStatus = Literal["allocated", "unmatched", "ambiguous"]


class CarryForwardError(ValueError):
    """Raised when carry-forward inputs violate the financial contract."""


@dataclass(frozen=True)
class CarryForwardRecord:
    record_id: str
    amount: Decimal
    currency: str
    business_date: date
    partition_key: str

    def __post_init__(self) -> None:
        if not self.record_id or not self.currency or not self.partition_key:
            raise CarryForwardError("Carry-forward records require identity, currency, and partition.")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount <= 0:
            raise CarryForwardError("Carry-forward amounts must be finite positive Decimal values.")


@dataclass(frozen=True)
class CarryForwardPolicy:
    date_window_days: int = 3660
    max_allocations: int = 10_000
    max_search_evaluations: int = 25_000
    amount_tolerance: Decimal = Decimal("0")
    max_window_cardinality: int = 16

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or value < 1
            for value in (self.max_allocations, self.max_search_evaluations, self.max_window_cardinality)
        ):
            raise CarryForwardError("Carry-forward ceilings must be positive integers.")
        if isinstance(self.date_window_days, bool) or self.date_window_days < 0:
            raise CarryForwardError("Carry-forward date window cannot be negative.")
        if (
            not isinstance(self.amount_tolerance, Decimal)
            or not self.amount_tolerance.is_finite()
            or self.amount_tolerance < 0
        ):
            raise CarryForwardError("Carry-forward amount tolerance must be a finite non-negative Decimal.")


@dataclass(frozen=True)
class CarryForwardAllocation:
    obligation_id: str
    settlement_id: str
    allocated_amount: Decimal
    obligation_residual: Decimal
    settlement_residual: Decimal
    sequence_rank: int
    reason_code: str = "CARRY_FORWARD_FIFO_ALLOCATION"


@dataclass(frozen=True)
class CarryForwardDecision:
    status: CarryForwardStatus
    allocations: tuple[CarryForwardAllocation, ...]
    unmatched_obligation_ids: tuple[str, ...]
    unmatched_settlement_ids: tuple[str, ...]
    reason_code: str
    candidate_count: int
    search_evaluations: int
    decision_digest: str


def allocate_carry_forward(
    obligations: tuple[CarryForwardRecord, ...],
    settlements: tuple[CarryForwardRecord, ...],
    policy: CarryForwardPolicy = CarryForwardPolicy(),
) -> CarryForwardDecision:
    """Allocate settlements FIFO to eligible obligations without posting effects."""
    if not obligations and not settlements:
        return _decision("unmatched", (), (), (), "CARRY_FORWARD_NO_INPUT", 0, 0)
    _validate_unique_ids(obligations, settlements)
    _validate_shared_scope(obligations, settlements)
    ordered_obligations = sorted(obligations, key=lambda record: (record.business_date, record.record_id))
    ordered_settlements = sorted(settlements, key=lambda record: (record.business_date, record.record_id))
    remaining = {record.record_id: record.amount for record in ordered_obligations}
    settlement_remaining = {record.record_id: record.amount for record in ordered_settlements}
    allocations: list[CarryForwardAllocation] = []
    candidate_count = 0
    evaluations = 0
    rank = 0
    for settlement in ordered_settlements:
        for obligation in ordered_obligations:
            if settlement_remaining[settlement.record_id] <= 0 or remaining[obligation.record_id] <= 0:
                continue
            evaluations += 1
            if evaluations > policy.max_search_evaluations or len(allocations) >= policy.max_allocations:
                return _decision(
                    "ambiguous",
                    tuple(allocations),
                    tuple(record.record_id for record in ordered_obligations if remaining[record.record_id] > 0),
                    tuple(record.record_id for record in ordered_settlements if settlement_remaining[record.record_id] > 0),
                    "CARRY_FORWARD_SEARCH_BUDGET_EXCEEDED",
                    candidate_count,
                    evaluations,
                )
            if settlement.business_date < obligation.business_date or (
                settlement.business_date - obligation.business_date
            ).days > policy.date_window_days:
                continue
            candidate_count += 1
            allocated = min(remaining[obligation.record_id], settlement_remaining[settlement.record_id])
            remaining[obligation.record_id] -= allocated
            settlement_remaining[settlement.record_id] -= allocated
            rank += 1
            allocations.append(
                CarryForwardAllocation(
                    obligation.record_id,
                    settlement.record_id,
                    allocated,
                    remaining[obligation.record_id],
                    settlement_remaining[settlement.record_id],
                    rank,
                )
            )
    unmatched_obligations = tuple(record.record_id for record in ordered_obligations if remaining[record.record_id] > 0)
    unmatched_settlements = tuple(record.record_id for record in ordered_settlements if settlement_remaining[record.record_id] > 0)
    status: CarryForwardStatus = "allocated" if allocations else "unmatched"
    reason = "CARRY_FORWARD_FIFO_ALLOCATED" if allocations else "CARRY_FORWARD_NO_ELIGIBLE_CANDIDATE"
    return _decision(status, tuple(allocations), unmatched_obligations, unmatched_settlements, reason, candidate_count, evaluations)


def allocate_sequence_window(
    obligations: tuple[CarryForwardRecord, ...],
    settlements: tuple[CarryForwardRecord, ...],
    policy: CarryForwardPolicy = CarryForwardPolicy(),
) -> CarryForwardDecision:
    """Match each settlement to one bounded contiguous obligation window.

    Windows are searched over canonical business-date order and cannot overlap.
    A unique best cost (absolute amount difference, then cardinality) is
    selected; equal-cost alternatives are returned as ``ambiguous`` rather than
    guessed.  This is proposal/evidence logic only and never posts an effect.
    """
    if not obligations and not settlements:
        return _decision("unmatched", (), (), (), "SEQUENCE_WINDOW_NO_INPUT", 0, 0)
    _validate_unique_ids(obligations, settlements)
    _validate_shared_scope(obligations, settlements)
    ordered_obligations = tuple(sorted(obligations, key=lambda record: (record.business_date, record.record_id)))
    ordered_settlements = tuple(sorted(settlements, key=lambda record: (record.business_date, record.record_id)))
    used_obligations: set[str] = set()
    matched_settlements: set[str] = set()
    allocations: list[CarryForwardAllocation] = []
    candidate_count = 0
    evaluations = 0
    rank = 0

    for settlement in ordered_settlements:
        candidates: list[tuple[Decimal, int, int, int, Decimal]] = []
        for start in range(len(ordered_obligations)):
            if ordered_obligations[start].record_id in used_obligations:
                continue
            running = Decimal("0")
            for end in range(start, min(len(ordered_obligations), start + policy.max_window_cardinality)):
                obligation = ordered_obligations[end]
                if obligation.record_id in used_obligations:
                    break
                evaluations += 1
                if evaluations > policy.max_search_evaluations:
                    return _decision(
                        "ambiguous",
                        tuple(allocations),
                        tuple(record.record_id for record in ordered_obligations if record.record_id not in used_obligations),
                        tuple(record.record_id for record in ordered_settlements if record.record_id not in matched_settlements),
                        "SEQUENCE_WINDOW_SEARCH_BUDGET_EXCEEDED",
                        candidate_count,
                        evaluations,
                    )
                if obligation.business_date > settlement.business_date:
                    break
                if (settlement.business_date - obligation.business_date).days > policy.date_window_days:
                    break
                running += obligation.amount
                difference = abs(running - settlement.amount)
                if difference <= policy.amount_tolerance:
                    candidates.append((difference, end - start + 1, start, end, running))

        candidate_count += len(candidates)
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        best = candidates[0]
        equal_cost = [item for item in candidates if item[0] == best[0] and item[1] == best[1]]
        if len(equal_cost) > 1:
            return _decision(
                "ambiguous",
                tuple(allocations),
                tuple(record.record_id for record in ordered_obligations if record.record_id not in used_obligations),
                tuple(record.record_id for record in ordered_settlements if record.record_id not in matched_settlements),
                "SEQUENCE_WINDOW_AMBIGUOUS_EQUAL_COST",
                candidate_count,
                evaluations,
            )
        _difference, _cardinality, start, end, running = best
        remaining_settlement = settlement.amount
        for obligation in ordered_obligations[start : end + 1]:
            used_obligations.add(obligation.record_id)
            remaining_settlement -= obligation.amount
            rank += 1
            allocations.append(
                CarryForwardAllocation(
                    obligation_id=obligation.record_id,
                    settlement_id=settlement.record_id,
                    allocated_amount=obligation.amount,
                    obligation_residual=Decimal("0"),
                    settlement_residual=remaining_settlement,
                    sequence_rank=rank,
                    reason_code="SEQUENCE_WINDOW_CONTIGUOUS_ALLOCATION",
                )
            )
        matched_settlements.add(settlement.record_id)

    unmatched_obligations = tuple(record.record_id for record in ordered_obligations if record.record_id not in used_obligations)
    unmatched_settlements = tuple(record.record_id for record in ordered_settlements if record.record_id not in matched_settlements)
    status: CarryForwardStatus = "allocated" if allocations else "unmatched"
    reason = "SEQUENCE_WINDOW_ALLOCATED" if allocations else "SEQUENCE_WINDOW_NO_ELIGIBLE_CANDIDATE"
    return _decision(status, tuple(allocations), unmatched_obligations, unmatched_settlements, reason, candidate_count, evaluations)


def _validate_unique_ids(
    obligations: tuple[CarryForwardRecord, ...], settlements: tuple[CarryForwardRecord, ...]
) -> None:
    for label, records in (("obligation", obligations), ("settlement", settlements)):
        ids = tuple(record.record_id for record in records)
        if len(ids) != len(set(ids)):
            raise CarryForwardError(f"Carry-forward {label} record identities must be unique.")


def _validate_shared_scope(
    obligations: tuple[CarryForwardRecord, ...], settlements: tuple[CarryForwardRecord, ...]
) -> None:
    all_records = obligations + settlements
    if not all_records:
        return
    if any(record.currency != all_records[0].currency for record in all_records) or any(
        record.partition_key != all_records[0].partition_key for record in all_records
    ):
        raise CarryForwardError("Carry-forward inputs must share one currency and partition.")


def _decision(status: CarryForwardStatus, allocations: tuple[CarryForwardAllocation, ...], obligations: tuple[str, ...], settlements: tuple[str, ...], reason: str, candidates: int, evaluations: int) -> CarryForwardDecision:
    payload = {"allocations": [_canonical(allocation) for allocation in allocations], "obligations": obligations, "settlements": settlements, "reason": reason, "status": status, "candidates": candidates, "evaluations": evaluations}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return CarryForwardDecision(status, allocations, obligations, settlements, reason, candidates, evaluations, digest)


def _canonical(allocation: CarryForwardAllocation) -> dict[str, object]:
    return {"obligation_id": allocation.obligation_id, "settlement_id": allocation.settlement_id, "allocated_amount": format(allocation.allocated_amount.normalize(), "f"), "obligation_residual": format(allocation.obligation_residual.normalize(), "f"), "settlement_residual": format(allocation.settlement_residual.normalize(), "f"), "sequence_rank": allocation.sequence_rank, "reason_code": allocation.reason_code}
