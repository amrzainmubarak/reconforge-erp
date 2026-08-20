from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from reconforge.domain.grouped_matching import (
    GroupedMatchingError,
    GroupedMatchPolicy,
    GroupedRecord,
    find_grouped_match,
    find_grouped_match_portfolio,
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


def test_partial_settlement_returns_settled_amount_and_visible_residual() -> None:
    decision = find_grouped_match(
        (_record("L1", "100"),),
        (_record("R1", "60"), _record("R2", "20")),
        GroupedMatchPolicy(mode="partial-settlement", max_right_cardinality=2),
    )

    assert decision.status == "matched"
    assert decision.reason_code == "PARTIAL_SETTLEMENT_PROPOSAL"
    assert decision.settled_amount == Decimal("80")
    assert decision.left_residual == Decimal("20")
    assert decision.right_residual == Decimal("0")
    assert "residual" in decision.explanation


def test_portfolio_selects_multiple_non_overlapping_groups() -> None:
    result = find_grouped_match_portfolio(
        (_record("L1", "100"), _record("L2", "50")),
        (_record("R1", "100"), _record("R2", "50")),
        GroupedMatchPolicy(mode="portfolio", max_left_cardinality=1, max_right_cardinality=1),
    )

    assert result.status == "matched"
    assert len(result.decisions) == 2
    assert result.unmatched_left_record_ids == result.unmatched_right_record_ids == ()
    assert {decision.left_record_ids for decision in result.decisions} == {("L1",), ("L2",)}


def test_portfolio_permutation_digest_is_stable() -> None:
    policy = GroupedMatchPolicy(mode="portfolio", max_left_cardinality=1, max_right_cardinality=1)
    first = find_grouped_match_portfolio(
        (_record("L1", "100"), _record("L2", "50")),
        (_record("R1", "100"), _record("R2", "50")),
        policy,
    )
    second = find_grouped_match_portfolio(
        (_record("L2", "50"), _record("L1", "100")),
        (_record("R2", "50"), _record("R1", "100")),
        policy,
    )
    assert first.portfolio_digest == second.portfolio_digest
    assert first.decisions == second.decisions


def test_portfolio_equal_maximum_cover_is_unresolved() -> None:
    result = find_grouped_match_portfolio(
        (_record("L1", "100"),),
        (_record("R1", "100"), _record("R2", "100")),
        GroupedMatchPolicy(mode="portfolio", max_left_cardinality=1, max_right_cardinality=1),
    )

    assert result.status == "ambiguous"
    assert result.decisions[0].reason_code == "GROUP_PORTFOLIO_AMBIGUOUS"


def test_portfolio_budget_is_fail_closed() -> None:
    result = find_grouped_match_portfolio(
        tuple(_record(f"L{index}", "1") for index in range(4)),
        tuple(_record(f"R{index}", "1") for index in range(4)),
        GroupedMatchPolicy(mode="portfolio", max_left_cardinality=2, max_right_cardinality=2, max_search_evaluations=1),
    )
    assert result.status == "ambiguous"
    assert result.decisions[0].reason_code == "GROUP_PORTFOLIO_SEARCH_BUDGET_EXCEEDED"


def test_portfolio_can_explicitly_select_partial_group_and_expose_residuals() -> None:
    result = find_grouped_match_portfolio(
        (_record("L1", "100"), _record("L2", "40")),
        (_record("R1", "75"), _record("R2", "40")),
        GroupedMatchPolicy(
            mode="portfolio",
            max_left_cardinality=1,
            max_right_cardinality=1,
            portfolio_allow_partial_settlement=True,
        ),
    )
    assert result.status == "matched"
    assert len(result.decisions) == 2
    partial = next(decision for decision in result.decisions if decision.left_record_ids == ("L1",))
    assert partial.reason_code == "GROUP_PORTFOLIO_PARTIAL_SETTLEMENT"
    assert partial.settled_amount == Decimal("75")
    assert partial.left_residual == Decimal("25")
    assert partial.right_residual == Decimal("0")


def test_portfolio_partial_flag_is_required_and_digest_bound() -> None:
    with pytest.raises(GroupedMatchingError, match="valid only in portfolio"):
        GroupedMatchPolicy(mode="many-to-many", portfolio_allow_partial_settlement=True)


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
