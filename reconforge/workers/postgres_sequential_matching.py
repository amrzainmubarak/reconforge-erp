"""PostgreSQL-worker adapter for bounded carry-forward and reversal matching."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from reconforge.application.matching_strategies import (
    MatchingStrategyRequest,
    MatchingStrategyResult,
    replay_result_envelope,
)
from reconforge.infrastructure.carry_forward_strategy import CarryForwardFifoStrategy
from reconforge.infrastructure.reversal_matching_strategy import ReversalPairingStrategy
from reconforge.workers.postgres_reconciliation import (
    ReconciliationExecutionContext,
    ReconciliationExecutionResult,
    ReconciliationInputPartition,
    ReconciliationPartitionResult,
)


class PostgresSequentialMatchingAdapterError(ValueError):
    """Raised when a sequential PostgreSQL matching partition is invalid."""


def _decimal_text(value: object) -> object:
    if not isinstance(value, Decimal):
        return value
    normalized = Decimal("0") if value == 0 else value.normalize()
    return format(normalized, "f")


def _record(value: Mapping[str, Any], *, partition_key: str) -> dict[str, object]:
    source_id = str(value.get("source_id") or value.get("id") or "").strip()
    attributes = value.get("attributes_json", value)
    if not isinstance(attributes, Mapping):
        raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL attributes must be an object.")
    item = {str(key): item_value for key, item_value in attributes.items()}
    item["id"] = source_id
    item["amount"] = _decimal_text(value.get("amount_decimal") or value.get("amount") or item.get("amount", ""))
    date_value = value.get("date_value") or value.get("date") or item.get("date", "")
    item["date"] = date_value.isoformat() if hasattr(date_value, "isoformat") else date_value
    item["currency"] = value.get("currency_code") or value.get("currency") or item.get("currency", "USD")
    item["partition"] = partition_key
    if not source_id or not str(item.get("amount", "")).strip() or not str(item.get("date", "")).strip():
        raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL records require id, amount, and date.")
    return item


def _request(
    context: ReconciliationExecutionContext,
    partition_key: str,
    left: Iterable[Mapping[str, Any]],
    right: Iterable[Mapping[str, Any]],
) -> MatchingStrategyRequest:
    rule = context.run.get("rule_json", {})
    if not isinstance(rule, Mapping):
        raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL rule_json must be an object.")
    mode = str(rule.get("matching_mode", "")).strip()
    if mode not in {"carry-forward", "sequence-window", "reversal-pairing"}:
        raise PostgresSequentialMatchingAdapterError("matching_mode must be an explicit sequential mode.")
    tolerance = rule.get("amount_tolerance", "0")
    if isinstance(tolerance, (float, bool)):
        raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL amount_tolerance must be exact text.")
    try:
        tolerance_text = str(Decimal(str(tolerance)))
        if not Decimal(tolerance_text).is_finite() or Decimal(tolerance_text) < 0:
            raise ValueError
    except (ValueError, ArithmeticError) as exc:
        raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL amount_tolerance is invalid.") from exc
    date_window = rule.get("date_window_days", 0)
    if isinstance(date_window, bool) or not isinstance(date_window, int) or not 0 <= date_window <= 3660:
        raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL date_window_days is outside its bound.")
    return MatchingStrategyRequest(
        left_records=tuple(_record(item, partition_key=partition_key) for item in left),
        right_records=tuple(_record(item, partition_key=partition_key) for item in right),
        amount_tolerance=tolerance_text,
        date_window_days=date_window,
        mode=mode,
    )


def _status(value: object) -> str:
    return {
        "allocated": "Matched",
        "matched": "Matched",
        "unmatched": "Unmatched",
        "ambiguous": "Ambiguous",
    }.get(str(value).strip().lower(), "Rejected")


def _ids(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return ()
    return tuple(sorted(str(item) for item in value))


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class PostgresSequentialMatchingAdapter:
    """Translate streamed PostgreSQL partitions through sequential strategies."""

    def __init__(self) -> None:
        self._strategies: dict[str, CarryForwardFifoStrategy | ReversalPairingStrategy] = {
            "carry-forward": CarryForwardFifoStrategy(),
            "sequence-window": CarryForwardFifoStrategy(),
            "reversal-pairing": ReversalPairingStrategy(),
        }

    def _lineage(
        self,
        *,
        decision: Mapping[str, object],
        output: MatchingStrategyResult,
        partition_key: str,
        strategy: CarryForwardFifoStrategy | ReversalPairingStrategy,
    ) -> dict[str, object]:
        manifest = strategy.manifest
        lineage = {
            "partition_key": partition_key,
            "strategy_id": manifest.id,
            "strategy_version": manifest.version,
            "strategy_manifest_digest": manifest.digest,
            "strategy_input_digest": getattr(output, "input_digest", ""),
            "strategy_result_digest": getattr(output, "decision_digest", ""),
            "explanation_schema": manifest.explanation_schema,
            "status": decision.get("status", ""),
            "reason_code": decision.get("reason_code", ""),
            "candidate_count": decision.get("candidate_count", 0),
            "search_evaluations": decision.get("search_evaluations", 0),
            "decision_digest": decision.get("decision_digest", ""),
        }
        return cast(dict[str, object], _json_safe(lineage))

    def _project(
        self,
        *,
        request: MatchingStrategyRequest,
        output: MatchingStrategyResult,
        strategy: CarryForwardFifoStrategy | ReversalPairingStrategy,
        partition_key: str,
    ) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
        if not output.results:
            raise PostgresSequentialMatchingAdapterError("Sequential strategy returned no decision.")
        decision = output.results[0]
        if not isinstance(decision, Mapping):
            raise PostgresSequentialMatchingAdapterError("Sequential strategy returned an invalid decision.")
        lineage = self._lineage(decision=decision, output=output, partition_key=partition_key, strategy=strategy)
        rows: list[Mapping[str, object]] = []
        mode = request.mode
        status = _status(decision.get("status"))
        if mode in {"carry-forward", "sequence-window"}:
            allocations = decision.get("allocations", ())
            if not isinstance(allocations, Sequence) or isinstance(allocations, (str, bytes, bytearray)):
                raise PostgresSequentialMatchingAdapterError("Sequential strategy allocations are invalid.")
            for allocation in allocations:
                if not isinstance(allocation, Mapping):
                    continue
                row_lineage = dict(lineage)
                row_lineage["allocation"] = _json_safe(allocation)
                rows.append(
                    {
                        "left_id": str(allocation.get("obligation_id", "")),
                        "right_id": str(allocation.get("settlement_id", "")),
                        "match_type": f"sequential:{mode}",
                        "confidence": "1" if status == "Matched" else "0",
                        "explanation": (
                            "Bounded contiguous sequence-window allocation with visible residuals."
                            if mode == "sequence-window"
                            else "Bounded FIFO carry-forward allocation with visible residuals."
                        ),
                        "amount_difference": "0",
                        "date_difference_days": None,
                        "status": status,
                        "reason_code": str(decision.get("reason_code", "")),
                        "lineage": row_lineage,
                    }
                )
            unmatched_left = _ids(decision.get("unmatched_obligation_ids", ()))
            unmatched_right = _ids(decision.get("unmatched_settlement_ids", ()))
        else:
            pairs = decision.get("pairs", ())
            if not isinstance(pairs, Sequence) or isinstance(pairs, (str, bytes, bytearray)):
                raise PostgresSequentialMatchingAdapterError("Sequential strategy pairs are invalid.")
            for pair in pairs:
                if not isinstance(pair, Mapping):
                    continue
                row_lineage = dict(lineage)
                row_lineage["pair"] = _json_safe(pair)
                rows.append(
                    {
                        "left_id": str(pair.get("original_id", "")),
                        "right_id": str(pair.get("reversal_id", "")),
                        "match_type": "sequential:reversal-pairing",
                        "confidence": "1" if status == "Matched" else "0",
                        "explanation": "Bounded reversal pairing preserves explicit links and candidate evidence.",
                        "amount_difference": str(_decimal_text(pair.get("absolute_difference", "0"))),
                        "date_difference_days": pair.get("date_delta_days"),
                        "status": status,
                        "reason_code": str(decision.get("reason_code", "")),
                        "lineage": row_lineage,
                    }
                )
            unmatched_left = _ids(decision.get("unmatched_original_ids", ()))
            unmatched_right = _ids(decision.get("unmatched_reversal_ids", ()))
        for source_id in unmatched_left:
            rows.append(
                {
                    "left_id": source_id,
                    "right_id": "",
                    "match_type": f"sequential:{mode}",
                    "confidence": "0",
                    "explanation": "The sequential strategy left this source record unmatched.",
                    "amount_difference": "0",
                    "date_difference_days": None,
                    "status": "Unmatched" if status != "Ambiguous" else status,
                    "reason_code": str(decision.get("reason_code", "")),
                    "lineage": lineage,
                }
            )
        for source_id in unmatched_right:
            rows.append(
                {
                    "left_id": "",
                    "right_id": source_id,
                    "match_type": f"sequential:{mode}",
                    "confidence": "0",
                    "explanation": "The sequential strategy left this source record unmatched.",
                    "amount_difference": "0",
                    "date_difference_days": None,
                    "status": "Unmatched" if status != "Ambiguous" else status,
                    "reason_code": str(decision.get("reason_code", "")),
                    "lineage": lineage,
                }
            )
        exceptions: tuple[Mapping[str, object], ...] = ()
        if status == "Ambiguous":
            # The durable exception schema intentionally accepts one concrete
            # source side per row.  A sequence-window ambiguity affects every
            # still-unresolved obligation and settlement, so preserve the
            # decision at that granularity instead of inventing a ``Both``
            # side that the database cannot represent.
            exception_rows: list[Mapping[str, object]] = []
            ambiguous_left_ids = tuple(
                sorted({str(row.get("left_id", "")) for row in rows if str(row.get("left_id", ""))})
            )
            ambiguous_right_ids = tuple(
                sorted({str(row.get("right_id", "")) for row in rows if str(row.get("right_id", ""))})
            )
            for side, source_ids in (
                ("Left", ambiguous_left_ids),
                ("Right", ambiguous_right_ids),
            ):
                for source_id in source_ids:
                    exception_rows.append(
                        {
                            "exception_type": "sequential_matching_ambiguity",
                            "source_side": side,
                            "source_id": source_id,
                            "title": "Sequential matching requires review",
                            "explanation": "The bounded sequential strategy did not select an unreviewed result.",
                            "severity": "High",
                            "risk_score": "1",
                            "reason_code": str(decision.get("reason_code", "")),
                            "owner_id": "",
                            "evidence": lineage,
                        }
                    )
            exceptions = tuple(exception_rows)
        return tuple(rows), exceptions

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
            strategy = self._strategies[request.mode]
            try:
                output = replay_result_envelope(strategy.execute(request), request, manifest=strategy.manifest)
                projected_results, projected_exceptions = self._project(
                    request=request,
                    output=output,
                    strategy=strategy,
                    partition_key=partition.partition_key,
                )
            except Exception as exc:
                raise PostgresSequentialMatchingAdapterError("Sequential PostgreSQL matching failed closed.") from exc
            results.append(
                ReconciliationPartitionResult(
                    partition_key=partition.partition_key,
                    input_count=partition.input_count,
                    results=tuple(cast(Mapping[str, object], _json_safe(item)) for item in projected_results),
                    exceptions=tuple(cast(Mapping[str, object], _json_safe(item)) for item in projected_exceptions),
                )
            )
        return tuple(results)

    def __call__(self, context: ReconciliationExecutionContext) -> ReconciliationExecutionResult:
        partitions = self.iter_partition_results(context)
        return ReconciliationExecutionResult(
            results=tuple(item for partition in partitions for item in partition.results),
            exceptions=tuple(item for partition in partitions for item in partition.exceptions),
        )


__all__ = ["PostgresSequentialMatchingAdapter", "PostgresSequentialMatchingAdapterError"]
