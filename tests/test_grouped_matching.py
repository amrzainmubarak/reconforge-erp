from datetime import date
from decimal import Decimal
from itertools import permutations

import pytest

from reconforge.domain.grouped_matching import (
    GroupedMatchingError,
    GroupedMatchPolicy,
    GroupedRecord,
    find_grouped_match,
)


def _record(
    record_id: str,
    amount: str,
    *,
    currency: str = "USD",
    day: int = 10,
    partition: str = "AR",
    fee: str = "0",
) -> GroupedRecord:
    return GroupedRecord(record_id, Decimal(amount), Decimal(fee), currency, date(2026, 1, day), partition)


@pytest.mark.parametrize(
    ("mode", "left", "right", "expected_left", "expected_right"),
    (
        ("one-to-many", (_record("L1", "100"),), (_record("R1", "40"), _record("R2", "60")), ("L1",), ("R1", "R2")),
        ("many-to-one", (_record("L1", "40"), _record("L2", "60")), (_record("R1", "100"),), ("L1", "L2"), ("R1",)),
        (
            "many-to-many",
            (_record("L1", "30"), _record("L2", "70")),
            (_record("R1", "45"), _record("R2", "55")),
            ("L1", "L2"),
            ("R1", "R2"),
        ),
    ),
)
def test_grouped_modes_enforce_true_sum_constraints(mode, left, right, expected_left, expected_right) -> None:
    decision = find_grouped_match(left, right, GroupedMatchPolicy(mode=mode))

    assert decision.status == "matched"
    assert decision.left_record_ids == expected_left
    assert decision.right_record_ids == expected_right
    assert decision.left_total == decision.right_total == Decimal("100")
    assert decision.reason_code == "GROUP_SUM_CONSTRAINT_SATISFIED"


def test_grouped_match_is_permutation_invariant_and_uses_stable_tie_break() -> None:
    left = (_record("L2", "100"), _record("L1", "100"))
    right = (_record("R3", "50"), _record("R1", "50"), _record("R2", "50"))
    policy = GroupedMatchPolicy(mode="one-to-many", max_right_cardinality=2)
    baseline = find_grouped_match(left[:1], right, policy)

    for right_order in permutations(right):
        assert find_grouped_match(left[:1], tuple(right_order), policy) == baseline
    assert baseline.status == "ambiguous"
    assert baseline.reason_code == "GROUP_MATCH_AMBIGUOUS"
    assert baseline.ambiguous_candidate_sets == (
        (("L2",), ("R1", "R2")),
        (("L2",), ("R1", "R3")),
        (("L2",), ("R2", "R3")),
    )
    assert "selection is intentionally unresolved" in baseline.explanation


def test_grouped_match_enforces_currency_partition_date_and_tolerance() -> None:
    left = (_record("L1", "100"),)
    right = (
        _record("R1", "40", currency="EUR"),
        _record("R2", "59.99", day=12),
        _record("R3", "40", partition="AP"),
    )
    policy = GroupedMatchPolicy(
        mode="one-to-many",
        amount_tolerance=Decimal("0.01"),
        date_window_days=1,
    )

    decision = find_grouped_match(left, right, policy)

    assert decision.status == "unmatched"
    assert decision.reason_code == "NO_GROUP_SATISFIED_CONSTRAINTS"


def test_grouped_match_reports_tied_minimum_candidates_as_ambiguous() -> None:
    decision = find_grouped_match(
        (_record("L1", "100"),),
        (
            _record("R1", "60"),
            _record("R2", "40"),
            _record("R3", "70"),
            _record("R4", "30"),
        ),
        GroupedMatchPolicy(mode="one-to-many", max_right_cardinality=2, amount_tolerance=Decimal("0")),
    )

    assert decision.status == "ambiguous"
    assert decision.reason_code == "GROUP_MATCH_AMBIGUOUS"
    assert decision.ambiguous_candidate_sets == (
        (("L1",), ("R1", "R2")),
        (("L1",), ("R3", "R4")),
    )


def test_grouped_match_fails_closed_when_search_budget_is_exceeded() -> None:
    left = (_record("L1", "100"),)
    right = tuple(_record(f"R{index}", "50") for index in range(1, 5))

    decision = find_grouped_match(
        left,
        right,
        GroupedMatchPolicy(mode="one-to-many", max_right_cardinality=3, max_search_evaluations=2),
    )

    assert decision.status == "ambiguous"
    assert decision.reason_code == "GROUP_SEARCH_BUDGET_EXCEEDED"
    assert decision.left_record_ids == ()
    assert decision.right_record_ids == ()


def test_grouped_match_cardinality_ceiling_is_a_hard_constraint() -> None:
    decision = find_grouped_match(
        (_record("L1", "100"),),
        (_record("R1", "20"), _record("R2", "30"), _record("R3", "50")),
        GroupedMatchPolicy(mode="one-to-many", max_right_cardinality=2),
    )

    assert decision.status == "unmatched"
    assert decision.reason_code == "NO_GROUP_SATISFIED_CONSTRAINTS"


def test_grouped_match_rejects_binary_or_non_finite_money_and_invalid_policy() -> None:
    with pytest.raises(GroupedMatchingError):
        GroupedRecord("L1", 1.5, Decimal("0"), "USD", date(2026, 1, 1), "AR")  # type: ignore[arg-type]
    with pytest.raises(GroupedMatchingError):
        _record("L1", "NaN")
    with pytest.raises(GroupedMatchingError):
        GroupedMatchPolicy(mode="many-to-many", max_left_cardinality=1)
    with pytest.raises(GroupedMatchingError):
        GroupedMatchPolicy(mode="unsupported")  # type: ignore[arg-type]


def test_grouped_matching_respects_gross_then_netting_mode() -> None:
    gross_match = find_grouped_match(
        (_record("L1", "100.00", fee="20.00"),),
        (_record("R1", "50.00", fee="10.00"), _record("R2", "50.00", fee="10.00")),
        GroupedMatchPolicy(mode="one-to-many"),
    )
    assert gross_match.status == "matched"
    assert gross_match.left_total == Decimal("100.00")
    assert gross_match.left_fee_total == Decimal("20.00")
    assert gross_match.right_total == Decimal("100.00")
    assert gross_match.right_fee_total == Decimal("20.00")
    assert gross_match.left_net_total == Decimal("100.00")
    assert gross_match.right_net_total == Decimal("100.00")

    net_mismatch = find_grouped_match(
        (_record("L1", "100.00", fee="20.00"),),
        (_record("R1", "50.00"), _record("R2", "50.00")),
        GroupedMatchPolicy(mode="one-to-many", netting_mode="net"),
    )
    assert net_mismatch.status == "unmatched"
    assert net_mismatch.left_net_total == Decimal("0")
    assert net_mismatch.right_net_total == Decimal("0")

    net_match = find_grouped_match(
        (_record("L1", "100.00", fee="20.00"),),
        (_record("R1", "50.00", fee="10.00"), _record("R2", "50.00", fee="10.00")),
        GroupedMatchPolicy(mode="one-to-many", netting_mode="net"),
    )
    assert net_match.status == "matched"
    assert net_match.left_net_total == Decimal("80.00")
    assert net_match.right_net_total == Decimal("80.00")
