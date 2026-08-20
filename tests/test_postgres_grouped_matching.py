from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.workers.postgres_grouped_matching import (
    PostgresGroupedMatchingAdapter,
    PostgresGroupedMatchingAdapterError,
    _request,
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
    first_row = cast(Mapping[str, object], first[0].results[0])
    assert first_row["status"] == "Matched"
    assert {
        (cast(Mapping[str, object], row)["left_id"], cast(Mapping[str, object], row)["right_id"])
        for row in first[0].results
    } == {
        ("L1", "R1"),
        ("L1", "R2"),
    }
    first_lineage = cast(Mapping[str, object], first_row["lineage"])
    assert first_lineage["strategy_id"] == "bounded-grouped-subset-sum"


@pytest.mark.parametrize("mode", ("one-to-many", "many-to-one", "many-to-many", "partial-settlement", "portfolio"))
def test_postgres_grouped_adapter_matches_direct_strategy_digest_for_every_supported_mode(mode: str) -> None:
    """The worker projection must not silently calculate a second algorithm."""

    context = _context(mode=mode)
    partition = ReconciliationInputPartition(
        partition_key="entity/A",
        left_inputs=context.left_inputs,
        right_inputs=context.right_inputs,
    )
    request = _request(context, partition.partition_key, partition.left_inputs, partition.right_inputs)
    direct = GroupedSubsetSumStrategy().execute(request)
    projected = PostgresGroupedMatchingAdapter().iter_partition_results(context)[0]

    projected_digests: set[str] = set()
    for raw_row in projected.results:
        row = cast(Mapping[str, object], raw_row)
        lineage = row.get("lineage")
        if isinstance(lineage, Mapping):
            projected_digests.add(str(lineage["strategy_result_digest"]))
    assert projected_digests == {direct.decision_digest}
    assert direct.decision_digest
    assert projected.results


def test_postgres_grouped_adapter_digest_changes_when_canonical_amount_changes() -> None:
    baseline = PostgresGroupedMatchingAdapter().iter_partition_results(_context())[0]
    changed_context = ReconciliationExecutionContext(
        run=_context().run,
        left_inputs=_context().left_inputs,
        right_inputs=(
            {"source_id": "R1", "amount_decimal": "40.01", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
            {"source_id": "R2", "amount_decimal": "60", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
        ),
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (
            ReconciliationInputPartition(
                partition_key="entity/A",
                left_inputs=_context().left_inputs,
                right_inputs=(
                    {"source_id": "R1", "amount_decimal": "40.01", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
                    {"source_id": "R2", "amount_decimal": "60", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
                ),
            ),
        ),
    )
    changed = PostgresGroupedMatchingAdapter().iter_partition_results(changed_context)[0]
    baseline_lineage = cast(Mapping[str, object], cast(Mapping[str, object], baseline.results[0])["lineage"])
    changed_lineage = cast(Mapping[str, object], cast(Mapping[str, object], changed.results[0])["lineage"])
    baseline_digest = str(baseline_lineage["strategy_result_digest"])
    changed_digest = str(changed_lineage["strategy_result_digest"])
    assert baseline_digest != changed_digest


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


def test_postgres_grouped_runtime_contract_is_in_source_distribution_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/workers/postgres_grouped_matching.py" in manifest
    assert "include tests/test_postgres_grouped_matching.py" in manifest
    assert "include tests/test_postgres_grouped_matching_runtime.py" in manifest
    assert "include docs/adr/0268-postgres-grouped-matching-runtime-parity.md" in manifest


def test_postgres_grouped_adapter_projects_unresolved_sources_and_review_exceptions() -> None:
    partition = ReconciliationInputPartition(
        partition_key="entity/unresolved",
        left_inputs=({"source_id": "L1", "amount_decimal": "100", "attributes_json": {"date": "2026-08-01"}},),
        right_inputs=({"source_id": "R1", "amount_decimal": "20", "attributes_json": {"date": "2026-08-01"}},),
    )
    context = ReconciliationExecutionContext(
        run={"rule_json": {"grouped_matching_mode": "one-to-many", "amount_tolerance": "0"}},
        left_inputs=partition.left_inputs,
        right_inputs=partition.right_inputs,
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (partition,),
    )

    result = PostgresGroupedMatchingAdapter().iter_partition_results(context)[0]

    assert {(row["left_id"], row["right_id"]) for row in result.results} == {("L1", ""), ("", "R1")}
    assert all(row["status"] == "Unmatched" for row in result.results)
    assert result.exceptions == ()


def test_postgres_grouped_adapter_projects_ambiguity_without_hidden_omissions() -> None:
    partition = ReconciliationInputPartition(
        partition_key="entity/ambiguous",
        left_inputs=({"source_id": "L1", "amount_decimal": "100", "attributes_json": {"date": "2026-08-01"}},),
        right_inputs=tuple(
            {"source_id": source_id, "amount_decimal": "50", "attributes_json": {"date": "2026-08-01"}}
            for source_id in ("R1", "R2", "R3")
        ),
    )
    context = ReconciliationExecutionContext(
        run={"rule_json": {"grouped_matching_mode": "one-to-many", "amount_tolerance": "0"}},
        left_inputs=partition.left_inputs,
        right_inputs=partition.right_inputs,
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (partition,),
    )

    result = PostgresGroupedMatchingAdapter().iter_partition_results(context)[0]

    assert len(result.results) == 4
    assert all(row["status"] == "Ambiguous" for row in result.results)
    assert len(result.exceptions) == 4
    assert {row["source_id"] for row in result.exceptions} == {"L1", "R1", "R2", "R3"}
