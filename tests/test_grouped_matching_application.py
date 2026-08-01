from decimal import Decimal

import pytest

from reconforge.application.grouped_matching import (
    GroupedMatchingApplicationService,
    GroupedMatchRequest,
)
from reconforge.domain.grouped_matching import GroupedMatchingError, GroupedMatchPolicy


def test_application_service_parses_exact_text_and_returns_explainable_group() -> None:
    decision = GroupedMatchingApplicationService().execute(
        GroupedMatchRequest(
            left_records=(
                {"id": "L1", "amount": "100.00", "currency": "usd", "date": "2026-01-10", "partition": "AR"},
            ),
            right_records=(
                {"id": "R1", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R2", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            policy=GroupedMatchPolicy(mode="one-to-many"),
        )
    )

    assert decision.status == "matched"
    assert decision.left_total == decision.right_total == Decimal("100.00")
    assert decision.currency == "USD"
    assert decision.group_id.startswith("MG-")
    assert len(decision.decision_digest) == 64


@pytest.mark.parametrize("bad_amount", (1.5, "NaN", "Infinity", "not-money"))
def test_application_service_rejects_inexact_or_malformed_amounts(bad_amount: object) -> None:
    request = GroupedMatchRequest(
        left_records=({"id": "L1", "amount": bad_amount, "currency": "USD", "date": "2026-01-10", "partition": "AR"},),
        right_records=(),
        policy=GroupedMatchPolicy(mode="one-to-many"),
    )

    with pytest.raises(GroupedMatchingError):
        GroupedMatchingApplicationService().execute(request)


def test_application_service_rejects_noncanonical_date_and_missing_field() -> None:
    service = GroupedMatchingApplicationService()
    base = {"id": "L1", "amount": "1", "currency": "USD", "date": "2026-1-1", "partition": "AR"}
    with pytest.raises(GroupedMatchingError):
        service.execute(GroupedMatchRequest((base,), (), GroupedMatchPolicy(mode="one-to-many")))
    missing_partition = {key: value for key, value in base.items() if key != "partition"}
    missing_partition["date"] = "2026-01-01"
    with pytest.raises(GroupedMatchingError, match="missing field: partition"):
        service.execute(GroupedMatchRequest((missing_partition,), (), GroupedMatchPolicy(mode="one-to-many")))


def test_application_service_supports_netting_and_custom_fee_fields() -> None:
    decision = GroupedMatchingApplicationService().execute(
        GroupedMatchRequest(
            left_records=(
                {
                    "id": "L1",
                    "amount": "100.00",
                    "currency": "USD",
                    "date": "2026-01-10",
                    "partition": "AR",
                    "fee_a": "20.00",
                },
                {
                    "id": "L2",
                    "amount": "20.00",
                    "currency": "USD",
                    "date": "2026-01-10",
                    "partition": "AR",
                    "fee_a": "5.00",
                },
            ),
            right_records=(
                {
                    "id": "R1",
                    "amount": "120.00",
                    "currency": "USD",
                    "date": "2026-01-10",
                    "partition": "AR",
                    "fee_b": "25.00",
                },
            ),
            policy=GroupedMatchPolicy(mode="many-to-one", netting_mode="net"),
            left_fee_field="fee_a",
            right_fee_field="fee_b",
        )
    )

    assert decision.status == "matched"
    assert decision.left_total == Decimal("120.00")
    assert decision.left_fee_total == Decimal("25.00")
    assert decision.right_fee_total == Decimal("25.00")
    assert decision.left_net_total == Decimal("95.00")
    assert decision.right_net_total == Decimal("95.00")


def test_application_service_parses_missing_fee_as_zero_in_gross_mode() -> None:
    decision = GroupedMatchingApplicationService().execute(
        GroupedMatchRequest(
            left_records=({"id": "L1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},),
            right_records=(
                {"id": "R1", "amount": "50.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R2", "amount": "50.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            policy=GroupedMatchPolicy(mode="one-to-many"),
            left_fee_field="fee",
            right_fee_field="fee",
        )
    )
    assert decision.status == "matched"
    assert decision.left_fee_total == Decimal("0")
    assert decision.right_fee_total == Decimal("0")


def test_application_service_reports_ambiguous_group_decision_for_equal_best_candidates() -> None:
    decision = GroupedMatchingApplicationService().execute(
        GroupedMatchRequest(
            left_records=({"id": "L1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},),
            right_records=(
                {"id": "R1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R3", "amount": "70.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R4", "amount": "30.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            policy=GroupedMatchPolicy(mode="one-to-many", max_right_cardinality=2),
        )
    )

    assert decision.status == "ambiguous"
    assert decision.reason_code == "GROUP_MATCH_AMBIGUOUS"
    assert decision.ambiguous_candidate_sets == (
        (("L1",), ("R1", "R2")),
        (("L1",), ("R3", "R4")),
    )


def test_application_service_converts_record_amounts_by_fx_when_target_currency_set() -> None:
    decision = GroupedMatchingApplicationService().execute(
        GroupedMatchRequest(
            left_records=(
                {"id": "L1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "L2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            right_records=(
                {"id": "R1", "amount": "200.00", "currency": "EUR", "date": "2026-01-10", "partition": "AR"},
            ),
            policy=GroupedMatchPolicy(mode="many-to-one"),
            target_currency="USD",
            fx_rates=(
                {
                    "base_currency": "EUR",
                    "quote_currency": "USD",
                    "rate": "0.5",
                    "rate_type": "spot",
                    "source": "ECB",
                    "effective_at": "2026-01-01",
                },
            ),
        )
    )
    assert decision.status == "matched"
    assert decision.left_total == Decimal("100.00")
    assert decision.right_total == Decimal("100.00")
    assert decision.currency == "USD"


def test_application_service_uses_inverse_fx_pair_when_only_reverse_rate_is_provided() -> None:
    decision = GroupedMatchingApplicationService().execute(
        GroupedMatchRequest(
            left_records=(
                {"id": "L1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "L2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            right_records=(
                {"id": "R1", "amount": "200.00", "currency": "EUR", "date": "2026-01-10", "partition": "AR"},
            ),
            policy=GroupedMatchPolicy(mode="many-to-one"),
            target_currency="USD",
            fx_rates=(
                {
                    "base_currency": "USD",
                    "quote_currency": "EUR",
                    "rate": "2",
                    "rate_type": "spot",
                    "source": "ECB",
                    "effective_at": "2026-01-01",
                },
            ),
        )
    )
    assert decision.status == "matched"


def test_application_service_rejects_cross_currency_without_fx_rates() -> None:
    with pytest.raises(GroupedMatchingError, match="requires FX rate data"):
        GroupedMatchingApplicationService().execute(
            GroupedMatchRequest(
                left_records=(
                    {"id": "L1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                    {"id": "L2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                ),
                right_records=(
                    {"id": "R1", "amount": "200.00", "currency": "EUR", "date": "2026-01-10", "partition": "AR"},
                ),
                policy=GroupedMatchPolicy(mode="many-to-one"),
                target_currency="USD",
            )
        )
