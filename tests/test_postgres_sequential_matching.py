from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from reconforge.workers.postgres_reconciliation import ReconciliationExecutionContext
from reconforge.workers.postgres_sequential_matching import (
    PostgresSequentialMatchingAdapter,
    PostgresSequentialMatchingAdapterError,
)


def _context(mode: str, left: tuple[dict[str, object], ...], right: tuple[dict[str, object], ...]) -> ReconciliationExecutionContext:
    return ReconciliationExecutionContext(
        run={"rule_json": {"matching_mode": mode, "date_window_days": 3, "amount_tolerance": "0"}},
        left_inputs=left,
        right_inputs=right,
        heartbeat=lambda completed: {"completed": completed},
        cancellation_requested=lambda: False,
    )


def _input(source_id: str, amount: str, when: str, *, reversal_of: str = "") -> dict[str, object]:
    return {
        "source_id": source_id,
        "amount_decimal": Decimal(amount),
        "date_value": date.fromisoformat(when),
        "currency_code": "USD",
        "attributes_json": {"currency": "USD", "reversal_of": reversal_of},
    }


def test_carry_forward_worker_projection_preserves_allocation_and_residual_lineage() -> None:
    result = PostgresSequentialMatchingAdapter()(
        _context(
            "carry-forward",
            (_input("O1", "100", "2026-08-01"),),
            (_input("S1", "60", "2026-08-02"),),
        )
    )
    matched = next(row for row in result.results if row["status"] == "Matched")
    assert (matched["left_id"], matched["right_id"]) == ("O1", "S1")
    assert matched["lineage"]["strategy_id"] == "bounded-carry-forward-fifo"
    assert matched["lineage"]["allocation"]["allocated_amount"] == "60"
    assert matched["lineage"]["allocation"]["obligation_residual"] == "40"
    assert result.exceptions == ()


def test_reversal_worker_projection_preserves_explicit_link_and_digest() -> None:
    result = PostgresSequentialMatchingAdapter()(
        _context(
            "reversal-pairing",
            (_input("J1", "100", "2026-08-01"),),
            (_input("R1", "-100", "2026-08-02", reversal_of="J1"),),
        )
    )
    assert len(result.results) == 1
    row = result.results[0]
    assert (row["left_id"], row["right_id"], row["status"]) == ("J1", "R1", "Matched")
    assert row["lineage"]["strategy_id"] == "bounded-reversal-pairing"
    assert row["lineage"]["pair"]["match_basis"] == "explicit-reversal-link"
    assert len(str(row["lineage"]["strategy_result_digest"])) == 64


def test_sequential_worker_rejects_implicit_or_malformed_modes() -> None:
    adapter = PostgresSequentialMatchingAdapter()
    with pytest.raises(PostgresSequentialMatchingAdapterError, match="explicit sequential mode"):
        adapter(_context("", (), ()))
    with pytest.raises(PostgresSequentialMatchingAdapterError, match="exact text"):
        adapter(
            ReconciliationExecutionContext(
                run={"rule_json": {"matching_mode": "carry-forward", "amount_tolerance": 0.1}},
                left_inputs=(),
                right_inputs=(),
                heartbeat=lambda completed: {"completed": completed},
                cancellation_requested=lambda: False,
            )
        )
