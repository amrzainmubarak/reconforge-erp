"""Bounded, explainable pairing of immutable financial reversals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ReversalStatus = Literal["matched", "unmatched", "ambiguous"]


class ReversalMatchingError(ValueError):
    """Raised when reversal-pairing inputs violate financial invariants."""


@dataclass(frozen=True)
class ReversalRecord:
    record_id: str
    amount: Decimal
    currency: str
    business_date: date
    partition_key: str
    reversal_of: str = ""

    def __post_init__(self) -> None:
        if not self.record_id or not self.currency or not self.partition_key:
            raise ReversalMatchingError("Reversal records require identity, currency, and partition.")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount == 0:
            raise ReversalMatchingError("Reversal amounts must be finite non-zero Decimal values.")
        if self.reversal_of == self.record_id:
            raise ReversalMatchingError("A reversal cannot reference itself.")


@dataclass(frozen=True)
class ReversalMatchingPolicy:
    date_window_days: int = 3660
    amount_tolerance: Decimal = Decimal("0")
    max_candidates: int = 10_000
    max_search_evaluations: int = 25_000

    def __post_init__(self) -> None:
        if not isinstance(self.amount_tolerance, Decimal) or not self.amount_tolerance.is_finite() or self.amount_tolerance < 0:
            raise ReversalMatchingError("Reversal tolerance must be a finite non-negative Decimal.")
        if any(isinstance(value, bool) or value < 1 for value in (self.max_candidates, self.max_search_evaluations)):
            raise ReversalMatchingError("Reversal ceilings must be positive integers.")
        if isinstance(self.date_window_days, bool) or self.date_window_days < 0:
            raise ReversalMatchingError("Reversal date window cannot be negative.")


@dataclass(frozen=True)
class ReversalPair:
    original_id: str
    reversal_id: str
    original_amount: Decimal
    reversal_amount: Decimal
    absolute_difference: Decimal
    date_delta_days: int
    match_basis: str
    candidate_count: int


@dataclass(frozen=True)
class ReversalDecision:
    status: ReversalStatus
    pairs: tuple[ReversalPair, ...]
    unmatched_original_ids: tuple[str, ...]
    unmatched_reversal_ids: tuple[str, ...]
    reason_code: str
    candidate_count: int
    search_evaluations: int
    decision_digest: str


def pair_reversals(
    originals: tuple[ReversalRecord, ...],
    reversals: tuple[ReversalRecord, ...],
    policy: ReversalMatchingPolicy = ReversalMatchingPolicy(),
) -> ReversalDecision:
    """Pair each reversal at most once; ambiguity is returned, never guessed."""
    ordered_originals = tuple(sorted(originals, key=lambda record: (record.business_date, record.record_id)))
    ordered_reversals = tuple(sorted(reversals, key=lambda record: (record.business_date, record.record_id)))
    all_records = ordered_originals + ordered_reversals
    if any(record.currency != all_records[0].currency for record in all_records) or any(
        record.partition_key != all_records[0].partition_key for record in all_records
    ) if all_records else False:
        raise ReversalMatchingError("Reversal inputs must share one currency and partition.")
    used_originals: set[str] = set()
    pairs: list[ReversalPair] = []
    total_candidates = 0
    evaluations = 0
    for reversal in ordered_reversals:
        candidates: list[tuple[ReversalRecord, str, Decimal, int]] = []
        for original in ordered_originals:
            if original.record_id in used_originals:
                continue
            evaluations += 1
            if evaluations > policy.max_search_evaluations:
                return _decision("ambiguous", tuple(pairs), ordered_originals, ordered_reversals, "REVERSAL_SEARCH_BUDGET_EXCEEDED", total_candidates, evaluations, used_originals)
            if original.amount * reversal.amount >= 0:
                continue
            delta = abs(original.amount + reversal.amount)
            day_delta = (reversal.business_date - original.business_date).days
            if day_delta < 0 or day_delta > policy.date_window_days or delta > policy.amount_tolerance:
                continue
            if reversal.reversal_of and reversal.reversal_of != original.record_id:
                continue
            basis = "explicit-reversal-link" if reversal.reversal_of else "opposite-amount-date-window"
            candidates.append((original, basis, delta, day_delta))
        total_candidates += len(candidates)
        if len(candidates) > policy.max_candidates:
            return _decision("ambiguous", tuple(pairs), ordered_originals, ordered_reversals, "REVERSAL_CANDIDATE_LIMIT_EXCEEDED", total_candidates, evaluations, used_originals)
        if not candidates:
            continue
        candidates.sort(key=lambda item: (0 if item[1] == "explicit-reversal-link" else 1, item[2], item[3], item[0].record_id))
        best_key = candidates[0][1:]
        tied = [candidate for candidate in candidates if candidate[1:] == best_key]
        if len(tied) > 1:
            return _decision("ambiguous", tuple(pairs), ordered_originals, ordered_reversals, "REVERSAL_AMBIGUOUS_CANDIDATES", total_candidates, evaluations, used_originals)
        original, basis, difference, day_delta = candidates[0]
        used_originals.add(original.record_id)
        pairs.append(ReversalPair(original.record_id, reversal.record_id, original.amount, reversal.amount, difference, day_delta, basis, len(candidates)))
    status: ReversalStatus = "matched" if pairs else "unmatched"
    reason = "REVERSAL_PAIRS_MATCHED" if pairs else "REVERSAL_NO_ELIGIBLE_CANDIDATE"
    return _decision(status, tuple(pairs), ordered_originals, ordered_reversals, reason, total_candidates, evaluations, used_originals)


def _decision(status: ReversalStatus, pairs: tuple[ReversalPair, ...], originals: tuple[ReversalRecord, ...], reversals: tuple[ReversalRecord, ...], reason: str, candidates: int, evaluations: int, used: set[str]) -> ReversalDecision:
    paired_reversals = {pair.reversal_id for pair in pairs}
    unmatched_originals = tuple(record.record_id for record in originals if record.record_id not in used)
    unmatched_reversals = tuple(record.record_id for record in reversals if record.record_id not in paired_reversals)
    payload = {"status": status, "pairs": [_canonical(pair) for pair in pairs], "unmatched_originals": unmatched_originals, "unmatched_reversals": unmatched_reversals, "reason": reason, "candidates": candidates, "evaluations": evaluations}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ReversalDecision(status, pairs, unmatched_originals, unmatched_reversals, reason, candidates, evaluations, digest)


def _canonical(pair: ReversalPair) -> dict[str, object]:
    return {"original_id": pair.original_id, "reversal_id": pair.reversal_id, "original_amount": format(pair.original_amount.normalize(), "f"), "reversal_amount": format(pair.reversal_amount.normalize(), "f"), "absolute_difference": format(pair.absolute_difference.normalize(), "f"), "date_delta_days": pair.date_delta_days, "match_basis": pair.match_basis, "candidate_count": pair.candidate_count}
