"""Bounded, deterministic grouped financial matching invariants."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import combinations
from typing import Literal

GroupedMatchMode = Literal["one-to-many", "many-to-one", "many-to-many", "partial-settlement", "portfolio"]
GroupedNettingMode = Literal["gross", "net"]
GroupedMatchStatus = Literal["matched", "unmatched", "ambiguous"]
GroupedMatchCandidateSet = tuple[tuple[str, ...], tuple[str, ...]]


class GroupedMatchingError(ValueError):
    """Raised when a grouped-match request violates financial invariants."""


@dataclass(frozen=True)
class GroupedRecord:
    record_id: str
    amount: Decimal
    fee: Decimal
    currency: str
    business_date: date
    partition_key: str

    def __post_init__(self) -> None:
        if not self.record_id or not self.currency or not self.partition_key:
            raise GroupedMatchingError("Grouped records require identity, currency, and partition key.")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise GroupedMatchingError("Grouped record amounts must be finite Decimal values.")
        if not isinstance(self.fee, Decimal) or not self.fee.is_finite():
            raise GroupedMatchingError("Grouped record fees must be finite Decimal values.")
        if self.fee < 0:
            raise GroupedMatchingError("Grouped record fees must be non-negative.")


@dataclass(frozen=True)
class GroupedMatchPolicy:
    mode: GroupedMatchMode
    amount_tolerance: Decimal = Decimal("0")
    date_window_days: int = 0
    max_left_cardinality: int = 4
    max_right_cardinality: int = 4
    max_search_evaluations: int = 25_000
    netting_mode: GroupedNettingMode = "gross"

    def __post_init__(self) -> None:
        if self.mode not in {"one-to-many", "many-to-one", "many-to-many", "partial-settlement", "portfolio"}:
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
        if self.netting_mode not in {"gross", "net"}:
            raise GroupedMatchingError("Grouped-match netting mode is not supported.")


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
    left_fee_total: Decimal
    right_fee_total: Decimal
    left_net_total: Decimal
    right_net_total: Decimal
    candidate_count: int
    search_evaluations: int
    reason_code: str
    netting_mode: str
    explanation: str
    tie_break: str
    ambiguous_candidate_sets: tuple[GroupedMatchCandidateSet, ...]
    decision_digest: str
    settled_amount: Decimal = Decimal("0")
    left_residual: Decimal = Decimal("0")
    right_residual: Decimal = Decimal("0")


@dataclass(frozen=True)
class GroupedMatchPortfolioResult:
    """Multiple non-overlapping grouped decisions with bounded replay evidence."""

    status: GroupedMatchStatus
    decisions: tuple[GroupedMatchDecision, ...]
    candidate_count: int
    search_evaluations: int
    unmatched_left_record_ids: tuple[str, ...]
    unmatched_right_record_ids: tuple[str, ...]
    portfolio_digest: str


@dataclass(frozen=True)
class _CandidateGroup:
    left: tuple[GroupedRecord, ...]
    right: tuple[GroupedRecord, ...]
    left_total: Decimal
    right_total: Decimal
    left_fee_total: Decimal
    right_fee_total: Decimal
    left_net_total: Decimal
    right_net_total: Decimal
    difference: Decimal
    date_span: int
    settled_amount: Decimal
    left_residual: Decimal
    right_residual: Decimal
    partial: bool

    @property
    def business_cost(self) -> tuple[Decimal, Decimal, Decimal, int]:
        if self.partial:
            return (Decimal("0"), -self.settled_amount, self.difference, self.date_span)
        return (Decimal("-1"), self.difference, Decimal(len(self.left) + len(self.right)), self.date_span)

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
    if policy.mode == "partial-settlement":
        return range(1, policy.max_left_cardinality + 1), range(1, policy.max_right_cardinality + 1)
    if policy.mode == "portfolio":
        return range(1, policy.max_left_cardinality + 1), range(1, policy.max_right_cardinality + 1)
    return (
        range(2, policy.max_left_cardinality + 1),
        range(2, policy.max_right_cardinality + 1),
    )


def _canonical_records(records: tuple[GroupedRecord, ...]) -> tuple[GroupedRecord, ...]:
    ordered = tuple(sorted(records, key=lambda record: record.record_id))
    if len({record.record_id for record in ordered}) != len(ordered):
        raise GroupedMatchingError("Grouped record identities must be unique on each side.")
    return ordered


def _aggregate_totals(
    records: tuple[GroupedRecord, ...], netting_mode: GroupedNettingMode
) -> tuple[Decimal, Decimal, Decimal]:
    gross = sum((record.amount for record in records), Decimal("0"))
    fees = sum((record.fee for record in records), Decimal("0"))
    net = gross - fees if netting_mode == "net" else gross
    return gross, fees, net


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
                            ambiguous_candidates=(),
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
                    left_total, left_fee_total, left_net_total = _aggregate_totals(left_group, policy.netting_mode)
                    right_total, right_fee_total, right_net_total = _aggregate_totals(right_group, policy.netting_mode)
                    difference = abs(left_net_total - right_net_total)
                    exact = difference <= policy.amount_tolerance
                    partial = (
                        policy.mode == "partial-settlement"
                        and not exact
                        and left_net_total > 0
                        and right_net_total > 0
                    )
                    if exact or partial:
                        settled_amount = min(left_net_total, right_net_total)
                        candidates.append(
                            _CandidateGroup(
                                left=left_group,
                                right=right_group,
                                left_total=left_total,
                                right_total=right_total,
                                left_fee_total=left_fee_total,
                                right_fee_total=right_fee_total,
                                left_net_total=left_net_total,
                                right_net_total=right_net_total,
                                difference=difference,
                                date_span=date_span,
                                settled_amount=settled_amount,
                                left_residual=left_net_total - settled_amount,
                                right_residual=right_net_total - settled_amount,
                                partial=partial,
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
            ambiguous_candidates=(),
        )
    selected = min(candidates, key=lambda candidate: (candidate.business_cost, candidate.stable_key))
    tied_candidates = tuple(
        candidate.stable_key
        for candidate in sorted(
            (candidate for candidate in candidates if candidate.business_cost == selected.business_cost),
            key=lambda candidate: candidate.stable_key,
        )
    )
    if len(tied_candidates) > 1:
        return _decision(
            status="ambiguous",
            policy=policy,
            candidate=None,
            candidate_count=len(candidates),
            evaluations=evaluations,
            reason_code="GROUP_MATCH_AMBIGUOUS",
            explanation=(
                f"Found {len(tied_candidates)} equivalent bounded-group matches with identical minimum cost; "
                "selection is intentionally unresolved pending governed review."
            ),
            ambiguous_candidates=tied_candidates,
        )
    equivalent_count = sum(candidate.business_cost == selected.business_cost for candidate in candidates)
    reason_code = "PARTIAL_SETTLEMENT_PROPOSAL" if selected.partial else "GROUP_SUM_CONSTRAINT_SATISFIED"
    explanation = (
        "Selected a bounded partial settlement proposal; residual balances remain visible for later settlement."
        if selected.partial
        else "Selected the lowest-cost bounded group; "
        f"stable record identities broke a tie across {equivalent_count} equivalent candidate(s)."
    )
    return _decision(
        status="matched",
        policy=policy,
        candidate=selected,
        candidate_count=len(candidates),
        evaluations=evaluations,
        reason_code=reason_code,
        explanation=explanation,
        ambiguous_candidates=(),
    )


def _portfolio_candidates(
    left: tuple[GroupedRecord, ...],
    right: tuple[GroupedRecord, ...],
    policy: GroupedMatchPolicy,
) -> tuple[list[_CandidateGroup], int, bool]:
    """Enumerate exact candidate groups under the declared portfolio budget."""

    candidates: list[_CandidateGroup] = []
    evaluations = 0
    for left_size in range(1, policy.max_left_cardinality + 1):
        for left_group in combinations(left, left_size):
            left_currencies = {record.currency for record in left_group}
            left_partitions = {record.partition_key for record in left_group}
            if len(left_currencies) != 1 or len(left_partitions) != 1:
                continue
            for right_size in range(1, policy.max_right_cardinality + 1):
                for right_group in combinations(right, right_size):
                    evaluations += 1
                    if evaluations > policy.max_search_evaluations:
                        return candidates, evaluations, True
                    all_records = left_group + right_group
                    if {record.currency for record in all_records} != left_currencies:
                        continue
                    if {record.partition_key for record in all_records} != left_partitions:
                        continue
                    dates = [record.business_date for record in all_records]
                    date_span = (max(dates) - min(dates)).days
                    if date_span > policy.date_window_days:
                        continue
                    left_total, left_fee_total, left_net_total = _aggregate_totals(left_group, policy.netting_mode)
                    right_total, right_fee_total, right_net_total = _aggregate_totals(right_group, policy.netting_mode)
                    difference = abs(left_net_total - right_net_total)
                    if difference > policy.amount_tolerance:
                        continue
                    candidates.append(
                        _CandidateGroup(
                            left=left_group,
                            right=right_group,
                            left_total=left_total,
                            right_total=right_total,
                            left_fee_total=left_fee_total,
                            right_fee_total=right_fee_total,
                            left_net_total=left_net_total,
                            right_net_total=right_net_total,
                            difference=difference,
                            date_span=date_span,
                            settled_amount=min(left_net_total, right_net_total),
                            left_residual=Decimal("0"),
                            right_residual=Decimal("0"),
                            partial=False,
                        )
                    )
    return candidates, evaluations, False


def _portfolio_digest(
    *,
    status: GroupedMatchStatus,
    decisions: tuple[GroupedMatchDecision, ...],
    unmatched_left: tuple[str, ...],
    unmatched_right: tuple[str, ...],
    candidate_count: int,
    search_evaluations: int,
) -> str:
    return _digest(
        {
            "candidate_count": candidate_count,
            "decisions": [decision.decision_digest for decision in decisions],
            "search_evaluations": search_evaluations,
            "status": status,
            "unmatched_left_record_ids": unmatched_left,
            "unmatched_right_record_ids": unmatched_right,
        }
    )


def find_grouped_match_portfolio(
    left_records: tuple[GroupedRecord, ...],
    right_records: tuple[GroupedRecord, ...],
    policy: GroupedMatchPolicy,
) -> GroupedMatchPortfolioResult:
    """Select several disjoint exact groups by maximum covered-record objective.

    The search is bounded by ``max_search_evaluations`` and leaves the whole
    partition unresolved when generation or selection exceeds that ceiling.
    """

    if policy.mode != "portfolio":
        raise GroupedMatchingError("Grouped portfolio matching requires portfolio mode.")
    left = _canonical_records(left_records)
    right = _canonical_records(right_records)
    decisions: tuple[GroupedMatchDecision, ...]
    candidates, evaluations, over_budget = _portfolio_candidates(left, right, policy)
    if over_budget:
        decision = _decision(
            status="ambiguous",
            policy=policy,
            candidate=None,
            candidate_count=len(candidates),
            evaluations=evaluations,
            reason_code="GROUP_PORTFOLIO_SEARCH_BUDGET_EXCEEDED",
            explanation="Portfolio candidate generation exceeded its deterministic budget; no group was selected.",
            ambiguous_candidates=(),
        )
        decisions = (decision,)
        return GroupedMatchPortfolioResult(
            status="ambiguous",
            decisions=decisions,
            candidate_count=len(candidates),
            search_evaluations=evaluations,
            unmatched_left_record_ids=tuple(record.record_id for record in left),
            unmatched_right_record_ids=tuple(record.record_id for record in right),
            portfolio_digest=_portfolio_digest(
                status="ambiguous",
                decisions=decisions,
                unmatched_left=tuple(record.record_id for record in left),
                unmatched_right=tuple(record.record_id for record in right),
                candidate_count=len(candidates),
                search_evaluations=evaluations,
            ),
        )
    if not candidates:
        decision = _decision(
            status="unmatched",
            policy=policy,
            candidate=None,
            candidate_count=0,
            evaluations=evaluations,
            reason_code="NO_PORTFOLIO_GROUP_SATISFIED_CONSTRAINTS",
            explanation="No bounded non-overlapping portfolio group satisfied the partition, date, and sum constraints.",
            ambiguous_candidates=(),
        )
        decisions = (decision,)
        return GroupedMatchPortfolioResult(
            status="unmatched",
            decisions=decisions,
            candidate_count=0,
            search_evaluations=evaluations,
            unmatched_left_record_ids=tuple(record.record_id for record in left),
            unmatched_right_record_ids=tuple(record.record_id for record in right),
            portfolio_digest=_portfolio_digest(
                status="unmatched",
                decisions=decisions,
                unmatched_left=tuple(record.record_id for record in left),
                unmatched_right=tuple(record.record_id for record in right),
                candidate_count=0,
                search_evaluations=evaluations,
            ),
        )

    ordered = tuple(sorted(candidates, key=lambda candidate: candidate.stable_key))
    best: list[_CandidateGroup] = []
    best_score: tuple[int, Decimal] | None = None
    equal_optima = 0
    nodes = 0
    def visit(position: int, used_left: frozenset[str], used_right: frozenset[str], selected: list[_CandidateGroup]) -> None:
        nonlocal best, best_score, equal_optima, nodes
        nodes += 1
        if nodes > policy.max_search_evaluations:
            raise GroupedMatchingError("portfolio selection search exceeded its deterministic budget")
        covered = sum(len(candidate.left) + len(candidate.right) for candidate in selected)
        cost = sum((candidate.difference for candidate in selected), Decimal("0"))
        score = (covered, -cost)
        if best_score is None or score > best_score:
            best_score = score
            best = list(selected)
            equal_optima = 0
        elif score == best_score and tuple(candidate.stable_key for candidate in selected) != tuple(
            candidate.stable_key for candidate in best
        ):
            equal_optima += 1
        for index in range(position, len(ordered)):
            candidate = ordered[index]
            if used_left.intersection(candidate.stable_key[0]) or used_right.intersection(candidate.stable_key[1]):
                continue
            visit(
                index + 1,
                used_left.union(candidate.stable_key[0]),
                used_right.union(candidate.stable_key[1]),
                [*selected, candidate],
            )

    try:
        visit(0, frozenset(), frozenset(), [])
    except GroupedMatchingError as exc:
        decision = _decision(
            status="ambiguous",
            policy=policy,
            candidate=None,
            candidate_count=len(candidates),
            evaluations=evaluations + nodes,
            reason_code="GROUP_PORTFOLIO_SEARCH_BUDGET_EXCEEDED",
            explanation=str(exc),
            ambiguous_candidates=(),
        )
        decisions = (decision,)
        return GroupedMatchPortfolioResult(
            status="ambiguous",
            decisions=decisions,
            candidate_count=len(candidates),
            search_evaluations=evaluations + nodes,
            unmatched_left_record_ids=tuple(record.record_id for record in left),
            unmatched_right_record_ids=tuple(record.record_id for record in right),
            portfolio_digest=_portfolio_digest(
                status="ambiguous",
                decisions=decisions,
                unmatched_left=tuple(record.record_id for record in left),
                unmatched_right=tuple(record.record_id for record in right),
                candidate_count=len(candidates),
                search_evaluations=evaluations + nodes,
            ),
        )

    used_left = {record.record_id for candidate in best for record in candidate.left}
    used_right = {record.record_id for candidate in best for record in candidate.right}
    unmatched_left = tuple(record.record_id for record in left if record.record_id not in used_left)
    unmatched_right = tuple(record.record_id for record in right if record.record_id not in used_right)
    if equal_optima:
        decision = _decision(
            status="ambiguous",
            policy=policy,
            candidate=None,
            candidate_count=len(candidates),
            evaluations=evaluations + nodes,
            reason_code="GROUP_PORTFOLIO_AMBIGUOUS",
            explanation="Several maximum-cover non-overlapping portfolios have equal cost; selection remains unresolved.",
            ambiguous_candidates=tuple(candidate.stable_key for candidate in ordered),
        )
        decisions = (decision,)
        status: GroupedMatchStatus = "ambiguous"
    else:
        decisions = tuple(
            _decision(
                status="matched",
                policy=policy,
                candidate=candidate,
                candidate_count=len(candidates),
                evaluations=evaluations + nodes,
                reason_code="GROUP_PORTFOLIO_MATCH",
                explanation="Selected a maximum-cover set of non-overlapping bounded groups.",
                ambiguous_candidates=(),
            )
            for candidate in sorted(best, key=lambda item: item.stable_key)
        )
        status = "matched" if decisions else "unmatched"
    return GroupedMatchPortfolioResult(
        status=status,
        decisions=decisions,
        candidate_count=len(candidates),
        search_evaluations=evaluations + nodes,
        unmatched_left_record_ids=unmatched_left,
        unmatched_right_record_ids=unmatched_right,
        portfolio_digest=_portfolio_digest(
            status=status,
            decisions=decisions,
            unmatched_left=unmatched_left,
            unmatched_right=unmatched_right,
            candidate_count=len(candidates),
            search_evaluations=evaluations + nodes,
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
    ambiguous_candidates: tuple[GroupedMatchCandidateSet, ...],
) -> GroupedMatchDecision:
    left_ids = candidate.stable_key[0] if candidate else ()
    right_ids = candidate.stable_key[1] if candidate else ()
    currency = candidate.left[0].currency if candidate else ""
    left_total = candidate.left_total if candidate else Decimal("0")
    right_total = candidate.right_total if candidate else Decimal("0")
    left_fee_total = candidate.left_fee_total if candidate else Decimal("0")
    right_fee_total = candidate.right_fee_total if candidate else Decimal("0")
    left_net_total = candidate.left_net_total if candidate else Decimal("0")
    right_net_total = candidate.right_net_total if candidate else Decimal("0")
    difference = candidate.difference if candidate else Decimal("0")
    settled_amount = candidate.settled_amount if candidate else Decimal("0")
    left_residual = candidate.left_residual if candidate else Decimal("0")
    right_residual = candidate.right_residual if candidate else Decimal("0")
    tie_break = (
        "exact-first-settled-amount-difference-date-span-stable-record-identities-v1"
        if policy.mode == "partial-settlement"
        else "difference-cardinality-date-span-stable-record-identities-v1"
    )
    payload = {
        "amount_difference": format(difference, "f"),
        "candidate_count": candidate_count,
        "currency": currency,
        "left_record_ids": left_ids,
        "left_total": format(left_total, "f"),
        "left_fee_total": format(left_fee_total, "f"),
        "left_net_total": format(left_net_total, "f"),
        "mode": policy.mode,
        "policy": {
            "amount_tolerance": format(policy.amount_tolerance, "f"),
            "date_window_days": policy.date_window_days,
            "max_left_cardinality": policy.max_left_cardinality,
            "max_right_cardinality": policy.max_right_cardinality,
            "max_search_evaluations": policy.max_search_evaluations,
            "netting_mode": policy.netting_mode,
        },
        "netting_mode": policy.netting_mode,
        "reason_code": reason_code,
        "right_record_ids": right_ids,
        "right_total": format(right_total, "f"),
        "right_fee_total": format(right_fee_total, "f"),
        "right_net_total": format(right_net_total, "f"),
        "settled_amount": format(settled_amount, "f"),
        "left_residual": format(left_residual, "f"),
        "right_residual": format(right_residual, "f"),
        "search_evaluations": evaluations,
        "status": status,
        "tie_break": tie_break,
        "ambiguous_candidate_sets": ambiguous_candidates,
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
        left_fee_total=left_fee_total,
        right_fee_total=right_fee_total,
        left_net_total=left_net_total,
        right_net_total=right_net_total,
        amount_difference=difference,
        candidate_count=candidate_count,
        search_evaluations=evaluations,
        reason_code=reason_code,
        netting_mode=policy.netting_mode,
        explanation=explanation,
        tie_break=tie_break,
        ambiguous_candidate_sets=ambiguous_candidates,
        decision_digest=digest,
        settled_amount=settled_amount,
        left_residual=left_residual,
        right_residual=right_residual,
    )
