from datetime import date
from decimal import Decimal

import pytest

from reconforge.domain.reversal_matching import (
    ReversalMatchingError,
    ReversalMatchingPolicy,
    ReversalRecord,
    pair_reversals,
)


def record(record_id: str, amount: str, day: int, *, reversal_of: str = "") -> ReversalRecord:
    return ReversalRecord(record_id, Decimal(amount), "USD", date(2026, 1, day), "ledger-1", reversal_of)


def test_reversal_pairing_requires_opposite_sign_and_preserves_explanation() -> None:
    result = pair_reversals((record("J-1", "100", 1),), (record("R-1", "-100", 2, reversal_of="J-1"),))
    assert result.status == "matched"
    assert result.pairs[0].match_basis == "explicit-reversal-link"
    assert result.pairs[0].absolute_difference == Decimal("0")
    assert result.unmatched_original_ids == ()


def test_reversal_pairing_is_permutation_stable_and_keeps_unmatched_visible() -> None:
    originals = (record("J-2", "50", 2), record("J-1", "75", 1))
    reversals = (record("R-2", "-50", 4), record("R-1", "-20", 4))
    first = pair_reversals(originals, reversals)
    second = pair_reversals(tuple(reversed(originals)), tuple(reversed(reversals)))
    assert first.decision_digest == second.decision_digest
    assert first.unmatched_original_ids == ("J-1",)
    assert first.unmatched_reversal_ids == ("R-1",)


def test_reversal_pairing_returns_ambiguity_for_equal_candidates() -> None:
    result = pair_reversals((record("J-1", "100", 1), record("J-2", "100", 1)), (record("R-1", "-100", 2),))
    assert result.status == "ambiguous"
    assert result.reason_code == "REVERSAL_AMBIGUOUS_CANDIDATES"


def test_reversal_pairing_fails_closed_on_budget_and_cross_partition() -> None:
    limited = pair_reversals((record("J-1", "100", 1), record("J-2", "80", 1)), (record("R-1", "-100", 2),), ReversalMatchingPolicy(max_search_evaluations=1))
    assert limited.status == "ambiguous"
    assert limited.reason_code == "REVERSAL_SEARCH_BUDGET_EXCEEDED"
    with pytest.raises(ReversalMatchingError, match="one currency and partition"):
        pair_reversals((record("J-1", "100", 1),), (ReversalRecord("R-1", Decimal("-100"), "USD", date(2026, 1, 2), "other"),))


def test_reversal_records_reject_zero_and_self_reference() -> None:
    with pytest.raises(ReversalMatchingError):
        ReversalRecord("J-1", Decimal("0"), "USD", date(2026, 1, 1), "ledger-1")
    with pytest.raises(ReversalMatchingError):
        ReversalRecord("J-1", Decimal("1"), "USD", date(2026, 1, 1), "ledger-1", "J-1")
