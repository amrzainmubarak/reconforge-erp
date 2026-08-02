"""PostgreSQL-worker adapter for bounded grouped matching partitions.

The adapter is deliberately persistence-free: the PostgreSQL worker owns input
streaming, leases, checkpoints, and result writes. This module translates one
partition into the closed grouped strategy request and returns bounded output
records suitable for the existing worker contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any, cast

from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.workers.postgres_reconciliation import (
    ReconciliationExecutionContext,
    ReconciliationInputPartition,
    ReconciliationPartitionResult,
)


class PostgresGroupedMatchingAdapterError(ValueError):
    """Raised when a PostgreSQL grouped-match partition is invalid."""


def _record(value: Mapping[str, Any], *, side: str, partition_key: str, rule: Mapping[str, Any]) -> dict[str, object]:
    source_id = str(value.get("source_id") or value.get("id") or "").strip()
    attributes = value.get("attributes_json", value)
    if not isinstance(attributes, Mapping):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL attributes must be an object.")
    item = {str(key): item_value for key, item_value in attributes.items()}
    item.setdefault("id", source_id)
    item.setdefault("amount", value.get("amount_decimal", value.get("amount", "")))
    item.setdefault("date", value.get("date_value", value.get("date", "")))
    item.setdefault("currency", value.get("currency_code", value.get("currency", "USD")))
    item.setdefault("partition", partition_key)
    if not source_id or not str(item.get("amount", "")).strip() or not str(item.get("date", "")).strip():
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL records require id, amount, and date.")
    if side not in {"Left", "Right"}:
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL side is invalid.")
    return item


def _request(context: ReconciliationExecutionContext, partition_key: str, left: Iterable[Mapping[str, Any]], right: Iterable[Mapping[str, Any]]) -> MatchingStrategyRequest:
    rule = context.run.get("rule_json", {})
    if not isinstance(rule, Mapping):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL rule_json must be an object.")
    mode = str(rule.get("grouped_matching_mode", rule.get("matching_mode", ""))).strip()
    if mode not in {"one-to-many", "many-to-one", "many-to-many", "partial-settlement", "portfolio"}:
        raise PostgresGroupedMatchingAdapterError("grouped_matching_mode must be an explicit supported mode.")
    tolerance = rule.get("amount_tolerance", "0")
    if isinstance(tolerance, (float, bool)):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL amount_tolerance must be exact text.")
    try:
        tolerance_text = str(Decimal(str(tolerance)))
    except Exception as exc:
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL amount_tolerance must be exact text.") from exc
    if not Decimal(tolerance_text).is_finite() or Decimal(tolerance_text) < 0:
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL amount_tolerance must be finite and non-negative.")
    date_window = rule.get("date_window_days", 0)
    if isinstance(date_window, bool) or not isinstance(date_window, int) or not 0 <= date_window <= 3660:
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL date_window_days is outside its bound.")
    netting_mode = str(rule.get("netting_mode", "gross"))
    allow_partial = rule.get("allow_partial_settlement", False)
    if not isinstance(allow_partial, bool):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL partial-settlement flag must be boolean.")
    return MatchingStrategyRequest(
        left_records=tuple(_record(item, side="Left", partition_key=partition_key, rule=rule) for item in left),
        right_records=tuple(_record(item, side="Right", partition_key=partition_key, rule=rule) for item in right),
        amount_tolerance=tolerance_text,
        date_window_days=date_window,
        mode=mode,
        netting_mode=netting_mode,  # type: ignore[arg-type]
        left_fee_field=str(rule.get("left_fee_field", "fee")),
        right_fee_field=str(rule.get("right_fee_field", "fee")),
        allow_partial_settlement=allow_partial,
    )


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class PostgresGroupedMatchingAdapter:
    """Translate streamed PostgreSQL partitions through the bounded strategy."""

    def __init__(self) -> None:
        self._strategy = GroupedSubsetSumStrategy()

    def iter_partition_results(
        self,
        context: ReconciliationExecutionContext,
        *,
        completed_partition_keys: frozenset[str] = frozenset(),
    ) -> tuple[ReconciliationPartitionResult, ...]:
        supplier = context.partition_supplier
        partitions = tuple(
            supplier()
            if supplier is not None
            else (
                ReconciliationInputPartition(
                    partition_key="default",
                    left_inputs=context.left_inputs,
                    right_inputs=context.right_inputs,
                ),
            )
        )
        results: list[ReconciliationPartitionResult] = []
        for partition in partitions:
            context.raise_if_cancelled()
            if partition.partition_key in completed_partition_keys:
                continue
            request = _request(context, partition.partition_key, partition.left_inputs, partition.right_inputs)
            try:
                output = self._strategy.execute(request)
            except Exception as exc:
                raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL matching failed closed.") from exc
            results.append(
                ReconciliationPartitionResult(
                    partition_key=partition.partition_key,
                    input_count=partition.input_count,
                    results=tuple(cast(Mapping[str, object], _json_safe(item)) for item in output.results),
                    exceptions=tuple(cast(Mapping[str, object], _json_safe(item)) for item in output.exceptions),
                )
            )
        return tuple(results)


__all__ = ["PostgresGroupedMatchingAdapter", "PostgresGroupedMatchingAdapterError"]
