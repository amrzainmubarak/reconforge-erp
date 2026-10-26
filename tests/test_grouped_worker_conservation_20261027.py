"""Regression proof for worker-side inexact grouped matching."""

from __future__ import annotations

from decimal import Decimal, Inexact, getcontext, localcontext

import pytest

from reconforge.workers.postgres_grouped_matching import (
    PostgresGroupedMatchingAdapter,
    PostgresGroupedMatchingAdapterError,
)
from reconforge.workers.postgres_reconciliation import ReconciliationExecutionContext


def _context(left_amount: object, right_amount: object) -> ReconciliationExecutionContext:
    attributes = {"date": "2026-08-01", "currency": "USD"}
    return ReconciliationExecutionContext(
        run={"rule_json": {"grouped_matching_mode": "portfolio", "date_window_days": 0, "amount_tolerance": "0"}},
        left_inputs=({"source_id": "L1", "amount_decimal": left_amount, "attributes_json": attributes},),
        right_inputs=({"source_id": "R1", "amount_decimal": right_amount, "attributes_json": attributes},),
        heartbeat=lambda _: {},
        cancellation_requested=lambda: False,
    )


def test_context_precision_cannot_silently_turn_unequal_database_values_into_a_match() -> None:
    left = Decimal("99999999999999999999.000000000000000001")
    right = Decimal("99999999999999999999.000000000000000002")
    assert left != right
    with localcontext() as context:
        context.prec = 28
        with pytest.raises(PostgresGroupedMatchingAdapterError, match="exact arithmetic"):
            PostgresGroupedMatchingAdapter()(_context(left, right))


def test_hostile_context_refuses_unequal_valid_usd_minor_unit_amounts() -> None:
    with localcontext() as context:
        context.prec = 3
        with pytest.raises(PostgresGroupedMatchingAdapterError, match="exact arithmetic"):
            PostgresGroupedMatchingAdapter()(_context(Decimal("1234.56"), Decimal("1234.57")))


def test_existing_result_and_global_decimal_context_are_unchanged() -> None:
    before = getcontext().copy()
    adapter = PostgresGroupedMatchingAdapter()
    result = adapter(_context(Decimal("10.00"), Decimal("10.00")))
    assert len(result.results) == 1
    assert result.results[0]["status"] == "Matched"
    assert result.results[0]["amount_difference"] == "0"
    assert getcontext().prec == before.prec and getcontext().flags == before.flags
    with localcontext() as context:
        context.flags[Inexact] = True
        assert adapter(_context(Decimal("10.00"), Decimal("10.00"))) == result
        assert context.flags[Inexact] is True
