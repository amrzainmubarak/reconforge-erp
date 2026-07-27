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
