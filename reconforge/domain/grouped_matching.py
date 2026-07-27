"""Bounded, deterministic grouped financial matching invariants."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import combinations
from typing import Literal

GroupedMatchMode = Literal["one-to-many", "many-to-one", "many-to-many"]
GroupedMatchStatus = Literal["matched", "unmatched", "ambiguous"]


class GroupedMatchingError(ValueError):
    """Raised when a grouped-match request violates financial invariants."""


@dataclass(frozen=True)
class GroupedRecord:
    record_id: str
    amount: Decimal
    currency: str
    business_date: date
    partition_key: str

    def __post_init__(self) -> None:
        if not self.record_id or not self.currency or not self.partition_key:
            raise GroupedMatchingError("Grouped records require identity, currency, and partition key.")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise GroupedMatchingError("Grouped record amounts must be finite Decimal values.")


@dataclass(frozen=True)
class GroupedMatchPolicy:
    mode: GroupedMatchMode
    amount_tolerance: Decimal = Decimal("0")
    date_window_days: int = 0
    max_left_cardinality: int = 4
    max_right_cardinality: int = 4
    max_search_evaluations: int = 25_000

    def __post_init__(self) -> None:
        if self.mode not in {"one-to-many", "many-to-one", "many-to-many"}:
            raise GroupedMatchingError("Grouped-match mode is not supported.")
        if not isinstance(self.amount_tolerance, Decimal) or not self.amount_tolerance.is_finite():
            raise GroupedMatchingError("Grouped-match tolerance must be a finite Decimal.")
        if self.amount_tolerance < 0:
            raise GroupedMatchingError("Grouped-match tolerance cannot be negative.")
        values = (self.max_left_cardinality, self.max_right_cardinality, self.max_search_evaluations)
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise GroupedMatchingError("Grouped-match ceilings must be positive integers.")
        if isinstance(self.date_window_days, bool) or self.date_window_days < 0:
            raise GroupedMatchingError("Grouped-match date window cannot be negative.")
        if self.mode == "one-to-many" and self.max_right_cardinality < 2:
            raise GroupedMatchingError("One-to-many matching requires right cardinality of at least two.")
        if self.mode == "many-to-one" and self.max_left_cardinality < 2:
            raise GroupedMatchingError("Many-to-one matching requires left cardinality of at least two.")
        if self.mode == "many-to-many" and (self.max_left_cardinality < 2 or self.max_right_cardinality < 2):
            raise GroupedMatchingError("Many-to-many matching requires cardinality of at least two on each side.")


@dataclass(frozen=True)
class GroupedMatchDecision:
    status: GroupedMatchStatus
    group_id: str
    mode: GroupedMatchMode
    left_record_ids: tuple[str, ...]
    right_record_ids: tuple[str, ...]
    currency: str
    left_total: Decimal
    right_total: Decimal
    amount_difference: Decimal
    candidate_count: int
    search_evaluations: int
    reason_code: str
    explanation: str
    tie_break: str
    decision_digest: str


@dataclass(frozen=True)
class _CandidateGroup:
    left: tuple[GroupedRecord, ...]
    right: tuple[GroupedRecord, ...]
    left_total: Decimal
    right_total: Decimal
    difference: Decimal
    date_span: int

    @property
    def business_cost(self) -> tuple[Decimal, int, int]:
        return (self.difference, len(self.left) + len(self.right), self.date_span)

    @property
    def stable_key(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return (
            tuple(record.record_id for record in self.left),
            tuple(record.record_id for record in self.right),
        )


def _cardinalities(policy: GroupedMatchPolicy) -> tuple[range, range]:
    if policy.mode == "one-to-many":
        return range(1, 2), range(2, policy.max_right_cardinality + 1)
    if policy.mode == "many-to-one":
        return range(2, policy.max_left_cardinality + 1), range(1, 2)
    return (
        range(2, policy.max_left_cardinality + 1),
        range(2, policy.max_right_cardinality + 1),
    )


def _canonical_records(records: tuple[GroupedRecord, ...]) -> tuple[GroupedRecord, ...]:
    ordered = tuple(sorted(records, key=lambda record: record.record_id))
    if len({record.record_id for record in ordered}) != len(ordered):
        raise GroupedMatchingError("Grouped record identities must be unique on each side.")
    return ordered


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def find_grouped_match(
    left_records: tuple[GroupedRecord, ...],
    right_records: tuple[GroupedRecord, ...],
    policy: GroupedMatchPolicy,
) -> GroupedMatchDecision:
    """Select one bounded sum-constrained group, or fail closed with evidence."""

    left = _canonical_records(left_records)
    right = _canonical_records(right_records)
    left_sizes, right_sizes = _cardinalities(policy)
    candidates: list[_CandidateGroup] = []
    evaluations = 0
    for left_size in left_sizes:
        for left_group in combinations(left, left_size):
            left_currencies = {record.currency for record in left_group}
            left_partitions = {record.partition_key for record in left_group}
            if len(left_currencies) != 1 or len(left_partitions) != 1:
                continue
            for right_size in right_sizes:
                for right_group in combinations(right, right_size):
                    evaluations += 1
                    if evaluations > policy.max_search_evaluations:
                        return _decision(
                            status="ambiguous",
                            policy=policy,
                            candidate=None,
                            candidate_count=len(candidates),
                            evaluations=evaluations,
                            reason_code="GROUP_SEARCH_BUDGET_EXCEEDED",
                            explanation="Grouped search exceeded its deterministic evaluation budget; no group was selected.",
                        )
                    all_records = left_group + right_group
                    if {record.currency for record in all_records} != left_currencies:
                        continue
                    if {record.partition_key for record in all_records} != left_partitions:
                        continue
                    dates = [record.business_date for record in all_records]
                    date_span = (max(dates) - min(dates)).days
                    if date_span > policy.date_window_days:
                        continue
                    left_total = sum((record.amount for record in left_group), Decimal("0"))
                    right_total = sum((record.amount for record in right_group), Decimal("0"))
                    difference = abs(left_total - right_total)
                    if difference <= policy.amount_tolerance:
                        candidates.append(
                            _CandidateGroup(
                                left=left_group,
                                right=right_group,
                                left_total=left_total,
                                right_total=right_total,
                                difference=difference,
                                date_span=date_span,
                            )
                        )
    if not candidates:
        return _decision(
            status="unmatched",
            policy=policy,
            candidate=None,
            candidate_count=0,
            evaluations=evaluations,
            reason_code="NO_GROUP_SATISFIED_CONSTRAINTS",
            explanation="No bounded group satisfied currency, partition, date, cardinality, and sum constraints.",
        )
    selected = min(candidates, key=lambda candidate: (candidate.business_cost, candidate.stable_key))
    equivalent_count = sum(candidate.business_cost == selected.business_cost for candidate in candidates)
    return _decision(
        status="matched",
        policy=policy,
        candidate=selected,
        candidate_count=len(candidates),
        evaluations=evaluations,
        reason_code="GROUP_SUM_CONSTRAINT_SATISFIED",
        explanation=(
            "Selected the lowest-cost bounded group; "
            f"stable record identities broke a tie across {equivalent_count} equivalent candidate(s)."
        ),
    )


def _decision(
    *,
    status: GroupedMatchStatus,
    policy: GroupedMatchPolicy,
    candidate: _CandidateGroup | None,
    candidate_count: int,
    evaluations: int,
    reason_code: str,
    explanation: str,
) -> GroupedMatchDecision:
    left_ids = candidate.stable_key[0] if candidate else ()
    right_ids = candidate.stable_key[1] if candidate else ()
    currency = candidate.left[0].currency if candidate else ""
    left_total = candidate.left_total if candidate else Decimal("0")
    right_total = candidate.right_total if candidate else Decimal("0")
    difference = candidate.difference if candidate else Decimal("0")
    payload = {
        "amount_difference": format(difference, "f"),
        "candidate_count": candidate_count,
        "currency": currency,
        "left_record_ids": left_ids,
        "left_total": format(left_total, "f"),
        "mode": policy.mode,
        "policy": {
            "amount_tolerance": format(policy.amount_tolerance, "f"),
            "date_window_days": policy.date_window_days,
            "max_left_cardinality": policy.max_left_cardinality,
            "max_right_cardinality": policy.max_right_cardinality,
            "max_search_evaluations": policy.max_search_evaluations,
        },
        "reason_code": reason_code,
        "right_record_ids": right_ids,
        "right_total": format(right_total, "f"),
        "search_evaluations": evaluations,
        "status": status,
        "tie_break": "difference-cardinality-date-span-stable-record-identities-v1",
    }
    digest = _digest(payload)
    return GroupedMatchDecision(
        status=status,
        group_id=f"MG-{digest[:20].upper()}" if candidate else "",
        mode=policy.mode,
        left_record_ids=left_ids,
        right_record_ids=right_ids,
        currency=currency,
        left_total=left_total,
        right_total=right_total,
        amount_difference=difference,
        candidate_count=candidate_count,
        search_evaluations=evaluations,
        reason_code=reason_code,
        explanation=explanation,
        tie_break="difference-cardinality-date-span-stable-record-identities-v1",
        decision_digest=digest,
    )
