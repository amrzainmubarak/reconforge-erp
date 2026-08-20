from datetime import date
from decimal import Decimal

import pytest

from reconforge.domain.carry_forward import (
    CarryForwardError,
    CarryForwardPolicy,
    CarryForwardRecord,
    allocate_carry_forward,
    allocate_sequence_window,
)


def record(record_id: str, amount: str, day: int, *, partition: str = "bank-1", currency: str = "USD") -> CarryForwardRecord:
    return CarryForwardRecord(record_id, Decimal(amount), currency, date(2026, 1, day), partition)


def test_fifo_allocates_oldest_and_keeps_residuals_visible() -> None:
    result = allocate_carry_forward(
        (record("O-2", "70", 2), record("O-1", "100", 1)),
        (record("S-1", "120", 3),),
    )
    assert result.status == "allocated"
    assert [(item.obligation_id, item.allocated_amount) for item in result.allocations] == [
        ("O-1", Decimal("100")),
        ("O-2", Decimal("20")),
    ]
    assert result.unmatched_obligation_ids == ("O-2",)
    assert result.unmatched_settlement_ids == ()


def test_date_window_and_partition_are_fail_closed() -> None:
    result = allocate_carry_forward((record("O-1", "10", 1),), (record("S-1", "10", 10),), CarryForwardPolicy(date_window_days=2))
    assert result.status == "unmatched"
    assert result.reason_code == "CARRY_FORWARD_NO_ELIGIBLE_CANDIDATE"
    with pytest.raises(CarryForwardError, match="one currency and partition"):
        allocate_carry_forward((record("O-1", "10", 1),), (record("S-1", "10", 2, partition="other"),))


def test_carry_forward_with_only_settlements_is_explicitly_unmatched() -> None:
    result = allocate_carry_forward((), (record("S-1", "10", 1),))
    assert result.status == "unmatched"
    assert result.reason_code == "CARRY_FORWARD_NO_ELIGIBLE_CANDIDATE"
    assert result.unmatched_settlement_ids == ("S-1",)


def test_digest_is_permutation_invariant_and_budget_is_explicit() -> None:
    first = allocate_carry_forward((record("O-2", "5", 2), record("O-1", "5", 1)), (record("S-1", "10", 3),))
    shuffled = allocate_carry_forward((record("O-1", "5", 1), record("O-2", "5", 2)), (record("S-1", "10", 3),))
    assert first.decision_digest == shuffled.decision_digest
    limited = allocate_carry_forward((record("O-1", "5", 1), record("O-2", "5", 2)), (record("S-1", "10", 3),), CarryForwardPolicy(max_search_evaluations=1))
    assert limited.status == "ambiguous"
    assert limited.reason_code == "CARRY_FORWARD_SEARCH_BUDGET_EXCEEDED"


def test_non_decimal_and_non_positive_amounts_are_rejected() -> None:
    with pytest.raises(CarryForwardError):
        CarryForwardRecord("O-1", 1.0, "USD", date(2026, 1, 1), "bank-1")  # type: ignore[arg-type]
    with pytest.raises(CarryForwardError):
        CarryForwardRecord("O-1", Decimal("0"), "USD", date(2026, 1, 1), "bank-1")


def test_sequence_window_allocates_one_contiguous_obligation_window() -> None:
    result = allocate_sequence_window(
        (
            record("O-2", "60", 2),
            record("O-1", "40", 1),
            record("O-3", "20", 3),
        ),
        (record("S-1", "100", 4),),
        CarryForwardPolicy(date_window_days=10, max_window_cardinality=2),
    )
    assert result.status == "allocated"
    assert [(item.obligation_id, item.allocated_amount) for item in result.allocations] == [
        ("O-1", Decimal("40")),
        ("O-2", Decimal("60")),
    ]
    assert result.unmatched_obligation_ids == ("O-3",)
    assert result.unmatched_settlement_ids == ()
    assert result.allocations[-1].reason_code == "SEQUENCE_WINDOW_CONTIGUOUS_ALLOCATION"


def test_sequence_window_is_permutation_stable_and_refuses_equal_cost_windows() -> None:
    obligations = (
        record("O-3", "50", 3),
        record("O-1", "50", 1),
        record("O-4", "50", 4),
        record("O-2", "50", 2),
    )
    first = allocate_sequence_window(obligations, (record("S-1", "100", 5),))
    shuffled = allocate_sequence_window(tuple(reversed(obligations)), (record("S-1", "100", 5),))
    assert first.decision_digest == shuffled.decision_digest
    assert first.status == "ambiguous"
    assert first.reason_code == "SEQUENCE_WINDOW_AMBIGUOUS_EQUAL_COST"
    assert first.allocations == ()


def test_sequence_window_budget_and_duplicate_identity_fail_closed() -> None:
    limited = allocate_sequence_window(
        (record("O-1", "40", 1), record("O-2", "60", 2)),
        (record("S-1", "100", 3),),
        CarryForwardPolicy(max_search_evaluations=1),
    )
    assert limited.status == "ambiguous"
    assert limited.reason_code == "SEQUENCE_WINDOW_SEARCH_BUDGET_EXCEEDED"
    with pytest.raises(CarryForwardError, match="identities must be unique"):
        allocate_sequence_window(
            (record("O-1", "10", 1), record("O-1", "10", 2)),
            (record("S-1", "20", 3),),
        )
