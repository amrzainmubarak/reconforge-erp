from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from reconforge.domain.grouped_matching import (
    GroupedMatchingError,
    GroupedMatchPolicy,
    GroupedRecord,
    find_grouped_match,
)


def _record(record_id: str, amount: str, *, fee: str = "0") -> GroupedRecord:
    return GroupedRecord(
        record_id=record_id,
        amount=Decimal(amount),
        fee=Decimal(fee),
        currency="USD",
        business_date=date(2026, 8, 1),
        partition_key="AR",
    )


def test_true_many_to_many_group_is_selected_with_exact_explanation() -> None:
    decision = find_grouped_match(
        (_record("L1", "30"), _record("L2", "70")),
        (_record("R1", "25"), _record("R2", "75")),
        GroupedMatchPolicy(mode="many-to-many"),
    )
    assert decision.status == "matched"
    assert decision.left_record_ids == ("L1", "L2")
    assert decision.right_record_ids == ("R1", "R2")
    assert decision.left_net_total == decision.right_net_total == Decimal("100")
    assert decision.reason_code == "GROUP_SUM_CONSTRAINT_SATISFIED"
    assert decision.tie_break == "difference-cardinality-date-span-stable-record-identities-v1"


def test_grouped_digest_is_invariant_to_input_permutation() -> None:
    policy = GroupedMatchPolicy(mode="many-to-many")
    first = find_grouped_match(
        (_record("L1", "30"), _record("L2", "70")),
        (_record("R1", "25"), _record("R2", "75")),
        policy,
    )
    second = find_grouped_match(
        (_record("L2", "70"), _record("L1", "30")),
        (_record("R2", "75"), _record("R1", "25")),
        policy,
    )
    assert first.decision_digest == second.decision_digest
    assert first.group_id == second.group_id


def test_search_budget_is_fail_closed_and_explainable() -> None:
    decision = find_grouped_match(
        tuple(_record(f"L{index}", "1") for index in range(4)),
        tuple(_record(f"R{index}", "1") for index in range(4)),
        GroupedMatchPolicy(mode="many-to-many", max_search_evaluations=1),
    )
    assert decision.status == "ambiguous"
    assert decision.reason_code == "GROUP_SEARCH_BUDGET_EXCEEDED"
    assert decision.search_evaluations == 2
    assert decision.group_id == ""


def test_netting_uses_explicit_non_negative_fees() -> None:
    decision = find_grouped_match(
        (_record("L1", "120", fee="20"), _record("L2", "20", fee="5")),
        (_record("R1", "100"), _record("R2", "15")),
        GroupedMatchPolicy(mode="many-to-many", netting_mode="net"),
    )
    assert decision.status == "matched"
    assert decision.left_fee_total == Decimal("25")
    assert decision.left_net_total == decision.right_net_total == Decimal("115")


def test_duplicate_identity_and_cross_partition_groups_fail_closed() -> None:
    duplicate = _record("same", "1")
    with pytest.raises(GroupedMatchingError, match="identities must be unique"):
        find_grouped_match((duplicate, duplicate), (_record("R", "2"),), GroupedMatchPolicy(mode="many-to-one"))
    other_partition = GroupedRecord(
        record_id="R-other",
        amount=Decimal("1"),
        fee=Decimal("0"),
        currency="USD",
        business_date=date(2026, 8, 1),
        partition_key="AP",
    )
    decision = find_grouped_match(
        (_record("L", "1"),),
        (other_partition,),
        GroupedMatchPolicy(mode="one-to-many"),
    )
    assert decision.status == "unmatched"
