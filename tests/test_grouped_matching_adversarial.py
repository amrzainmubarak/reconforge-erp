from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from reconforge.application.grouped_matching import (
    GroupedMatchingApplicationService,
    GroupedMatchRequest,
)
from reconforge.domain.grouped_matching import (
    GroupedMatchPolicy,
    GroupedRecord,
    find_grouped_match,
)


def _record(
    record_id: str,
    amount: str,
    *,
    fee: str = "0",
    currency: str = "USD",
    partition: str = "SETTLEMENT",
) -> GroupedRecord:
    return GroupedRecord(
        record_id=record_id,
        amount=Decimal(amount),
        fee=Decimal(fee),
        currency=currency,
        business_date=date(2026, 8, 6),
        partition_key=partition,
    )


def test_dense_fee_netting_equal_optima_stays_explicitly_ambiguous() -> None:
    decision = find_grouped_match(
        (
            _record("L1", "70", fee="10"),
            _record("L2", "50", fee="10"),
        ),
        (
            _record("R1", "65", fee="5"),
            _record("R2", "45", fee="5"),
            _record("R3", "65", fee="5"),
            _record("R4", "45", fee="5"),
        ),
        GroupedMatchPolicy(mode="many-to-many", netting_mode="net"),
    )

    assert decision.status == "ambiguous"
    assert decision.reason_code == "GROUP_MATCH_AMBIGUOUS"
    assert decision.ambiguous_candidate_sets == (
        (("L1", "L2"), ("R1", "R2")),
        (("L1", "L2"), ("R1", "R4")),
        (("L1", "L2"), ("R2", "R3")),
        (("L1", "L2"), ("R3", "R4")),
    )
    assert decision.left_net_total == decision.right_net_total == Decimal("0")


def test_dense_fee_fx_netting_is_permutation_stable_and_exact() -> None:
    request = GroupedMatchRequest(
        left_records=(
            {
                "id": "L1",
                "amount": "100.00",
                "currency": "USD",
                "date": "2026-08-06",
                "partition": "SETTLEMENT",
                "fee": "2.00",
            },
        ),
        right_records=(
            {
                "id": "R1",
                "amount": "120.00",
                "currency": "EUR",
                "date": "2026-08-06",
                "partition": "SETTLEMENT",
                "fee": "4.00",
            },
            {
                "id": "R2",
                "amount": "80.00",
                "currency": "EUR",
                "date": "2026-08-06",
                "partition": "SETTLEMENT",
                "fee": "0.00",
            },
        ),
        policy=GroupedMatchPolicy(mode="one-to-many", netting_mode="net"),
        left_fee_field="fee",
        right_fee_field="fee",
        target_currency="USD",
        fx_rates=(
            {
                "base_currency": "EUR",
                "quote_currency": "USD",
                "rate": "0.5",
                "rate_type": "spot",
                "source": "synthetic-reference",
                "effective_at": "2026-08-01",
            },
        ),
    )
    service = GroupedMatchingApplicationService()
    decision = service.execute(request)
    reordered = service.execute(
        replace(request, right_records=tuple(reversed(request.right_records)))
    )

    assert decision.status == "matched"
    assert decision.decision_digest == reordered.decision_digest
    assert decision.currency == "USD"
    assert decision.left_total == decision.right_total == Decimal("100.00")
    assert decision.left_fee_total == decision.right_fee_total == Decimal("2.00")
    assert decision.left_net_total == decision.right_net_total == Decimal("98.00")
    assert decision.amount_difference == Decimal("0.00")


def test_dense_budget_refusal_is_permutation_stable_and_has_no_partial_result() -> None:
    policy = GroupedMatchPolicy(mode="many-to-many", max_search_evaluations=3)
    left = tuple(_record(f"L{index}", "10") for index in range(3))
    right = tuple(_record(f"R{index}", "10") for index in range(3))

    first = find_grouped_match(left, right, policy)
    second = find_grouped_match(tuple(reversed(left)), tuple(reversed(right)), policy)

    assert first.status == second.status == "ambiguous"
    assert first.reason_code == second.reason_code == "GROUP_SEARCH_BUDGET_EXCEEDED"
    assert first.decision_digest == second.decision_digest
    assert first.left_record_ids == first.right_record_ids == ()
    assert first.group_id == ""


def test_dense_candidates_reject_cross_partition_and_currency_without_guessing() -> None:
    policy = GroupedMatchPolicy(mode="many-to-many")
    left = (_record("L1", "50"), _record("L2", "50"))
    right = (
        _record("R1", "50", partition="OTHER"),
        _record("R2", "50", currency="EUR"),
    )

    decision = find_grouped_match(left, right, policy)

    assert decision.status == "unmatched"
    assert decision.reason_code == "NO_GROUP_SATISFIED_CONSTRAINTS"
    assert decision.left_record_ids == decision.right_record_ids == ()
