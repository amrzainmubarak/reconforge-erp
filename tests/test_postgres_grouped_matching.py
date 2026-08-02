from __future__ import annotations

import pytest

from reconforge.workers.postgres_grouped_matching import (
    PostgresGroupedMatchingAdapter,
    PostgresGroupedMatchingAdapterError,
)
from reconforge.workers.postgres_reconciliation import (
    ReconciliationExecutionContext,
    ReconciliationInputPartition,
)


def _context(*, mode: str = "one-to-many", reverse: bool = False) -> ReconciliationExecutionContext:
    left = (
        {"source_id": "L1", "amount_decimal": "100", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
    )
    right = (
        {"source_id": "R1", "amount_decimal": "40", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
        {"source_id": "R2", "amount_decimal": "60", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
    )
    partition = ReconciliationInputPartition(
        partition_key="entity/A",
        left_inputs=tuple(reversed(left)) if reverse else left,
        right_inputs=tuple(reversed(right)) if reverse else right,
    )
    return ReconciliationExecutionContext(
        run={"rule_json": {"grouped_matching_mode": mode, "date_window_days": 0, "amount_tolerance": "0"}},
        left_inputs=partition.left_inputs,
        right_inputs=partition.right_inputs,
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (partition,),
    )


def test_postgres_grouped_adapter_is_partition_permutation_invariant() -> None:
    adapter = PostgresGroupedMatchingAdapter()
    first = adapter.iter_partition_results(_context())
    second = adapter.iter_partition_results(_context(reverse=True))

    assert first == second
    assert first[0].partition_key == "entity/A"
    assert first[0].results[0]["status"] == "matched"


def test_postgres_grouped_adapter_skips_completed_checkpoint() -> None:
    result = PostgresGroupedMatchingAdapter().iter_partition_results(
        _context(), completed_partition_keys=frozenset({"entity/A"})
    )
    assert result == ()


@pytest.mark.parametrize("mode", ("", "unsupported"))
def test_postgres_grouped_adapter_requires_explicit_supported_mode(mode: str) -> None:
    with pytest.raises(PostgresGroupedMatchingAdapterError, match="grouped_matching_mode"):
        PostgresGroupedMatchingAdapter().iter_partition_results(_context(mode=mode))


def test_postgres_grouped_adapter_rejects_binary_tolerance() -> None:
    context = _context()
    context = ReconciliationExecutionContext(
        run={"rule_json": {"grouped_matching_mode": "one-to-many", "amount_tolerance": 0.1}},
        left_inputs=context.left_inputs,
        right_inputs=context.right_inputs,
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
    )
    with pytest.raises(PostgresGroupedMatchingAdapterError, match="exact text"):
        PostgresGroupedMatchingAdapter().iter_partition_results(context)
