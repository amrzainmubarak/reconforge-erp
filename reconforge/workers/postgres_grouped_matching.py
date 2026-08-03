"""PostgreSQL-worker adapter for bounded grouped matching partitions.

The adapter is deliberately persistence-free: the PostgreSQL worker owns input
streaming, leases, checkpoints, and result writes. This module translates one
partition into the closed grouped strategy request and returns bounded output
records suitable for the existing worker contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.workers.postgres_reconciliation import (
    ReconciliationExecutionContext,
    ReconciliationExecutionResult,
    ReconciliationInputPartition,
    ReconciliationPartitionResult,
)


class PostgresGroupedMatchingAdapterError(ValueError):
    """Raised when a PostgreSQL grouped-match partition is invalid."""


def _decimal_text(value: object) -> object:
    if not isinstance(value, Decimal):
        return value
    normalized = Decimal("0") if value == 0 else value.normalize()
    return format(normalized, "f")


def _record(value: Mapping[str, Any], *, side: str, partition_key: str, rule: Mapping[str, Any]) -> dict[str, object]:
    source_id = str(value.get("source_id") or value.get("id") or "").strip()
    attributes = value.get("attributes_json", value)
    if not isinstance(attributes, Mapping):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL attributes must be an object.")
    item = {str(key): item_value for key, item_value in attributes.items()}
    # Database-owned canonical columns always win over JSON attributes.  An
    # input producer must not be able to change identity or financial values by
    # shadowing them in attributes_json.
    item["id"] = source_id
    item["amount"] = _decimal_text(value.get("amount_decimal") or value.get("amount") or item.get("amount", ""))
    date_value = value.get("date_value") or value.get("date") or item.get("date", "")
    item["date"] = date_value.isoformat() if hasattr(date_value, "isoformat") else date_value
    item["currency"] = value.get("currency_code") or value.get("currency") or item.get("currency", "USD")
    item["partition"] = partition_key
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
    raw_fx_rates = rule.get("fx_rates", ())
    if isinstance(raw_fx_rates, (str, bytes, bytearray)) or not isinstance(raw_fx_rates, Sequence):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL fx_rates must be a bounded sequence of objects.")
    fx_rates: list[Mapping[str, object]] = []
    for profile in raw_fx_rates:
        if not isinstance(profile, Mapping):
            raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL FX profiles must be objects.")
        fx_rates.append({str(key): item for key, item in profile.items()})
    target_currency = rule.get("target_currency", "")
    if not isinstance(target_currency, str):
        raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL target_currency must be text.")
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
        target_currency=target_currency,
        fx_rates=tuple(fx_rates),
    )


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text in {"", "-0"} else text
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class PostgresGroupedMatchingAdapter:
    """Translate streamed PostgreSQL partitions through the bounded strategy."""

    def __init__(self) -> None:
        self._strategy = GroupedSubsetSumStrategy()

    def _decision_lineage(self, decision: Mapping[str, object], *, partition_key: str, output: object) -> dict[str, object]:
        """Return bounded, replayable evidence for one persisted group."""

        fields = (
            "group_id",
            "mode",
            "left_record_ids",
            "right_record_ids",
            "currency",
            "left_total",
            "right_total",
            "amount_difference",
            "left_fee_total",
            "right_fee_total",
            "left_net_total",
            "right_net_total",
            "netting_mode",
            "candidate_count",
            "search_evaluations",
            "reason_code",
            "tie_break",
            "decision_digest",
            "settled_amount",
            "left_residual",
            "right_residual",
        )
        lineage = {key: decision[key] for key in fields if key in decision}
        lineage.update(
            {
                "partition_key": partition_key,
                "strategy_id": self._strategy.manifest.id,
                "strategy_version": self._strategy.manifest.version,
                "strategy_manifest_digest": self._strategy.manifest.digest,
                "strategy_input_digest": getattr(output, "input_digest", ""),
                "strategy_result_digest": getattr(output, "decision_digest", ""),
                "explanation_schema": self._strategy.manifest.explanation_schema,
            }
        )
        return cast(dict[str, object], _json_safe(lineage))

    @staticmethod
    def _status(value: object) -> str:
        statuses = {
            "matched": "Matched",
            "unmatched": "Unmatched",
            "ambiguous": "Ambiguous",
            "invalid": "Invalid",
            "duplicate": "Duplicate",
            "rejected": "Rejected",
        }
        return statuses.get(str(value).strip().lower(), "Rejected")

    @staticmethod
    def _record_ids(value: object) -> tuple[str, ...]:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
            return ()
        return tuple(sorted(str(item) for item in value))

    def _decision_records(
        self,
        decision: Mapping[str, object],
        *,
        lineage: Mapping[str, object],
    ) -> tuple[dict[str, object], ...]:
        """Project one grouped decision onto the legacy per-record result table.

        The hosted result schema is intentionally one left/right identity per
        row.  A grouped decision therefore emits the deterministic Cartesian
        edge set for matched groups, or one single-sided row per unresolved
        source.  Full group totals and identities remain in lineage.
        """

        left_ids = self._record_ids(decision.get("left_record_ids", ()))
        right_ids = self._record_ids(decision.get("right_record_ids", ()))
        status = self._status(decision.get("status"))
        match_type = f"grouped:{str(decision.get('mode', 'unknown'))}"[:64]
        confidence = "1" if status == "Matched" else "0"
        difference = str(_json_safe(decision.get("amount_difference", "0")))
        explanation = str(decision.get("explanation", "Grouped matching decision."))[:4000]
        reason = str(decision.get("reason_code", ""))[:64]
        edges: list[tuple[str, str]] = []
        if status == "Matched" and left_ids and right_ids:
            edges = [(left_id, right_id) for left_id in left_ids for right_id in right_ids]
        else:
            edges = [(left_id, "") for left_id in left_ids] + [("", right_id) for right_id in right_ids]
        records: list[dict[str, object]] = []
        for index, (left_id, right_id) in enumerate(edges):
            records.append(
                {
                    "left_id": left_id,
                    "right_id": right_id,
                    "match_type": match_type,
                    "confidence": confidence,
                    "explanation": explanation,
                    "amount_difference": difference if index == 0 else "0",
                    "date_difference_days": None,
                    "status": status,
                    "reason_code": reason,
                    "lineage": dict(lineage),
                }
            )
        return tuple(records)

    @staticmethod
    def _decision_exceptions(
        decision: Mapping[str, object], *, lineage: Mapping[str, object]
    ) -> tuple[dict[str, object], ...]:
        if str(decision.get("status", "")).lower() != "ambiguous":
            return ()
        explanation = str(decision.get("explanation", "Grouped matching was ambiguous."))[:4000]
        reason = str(decision.get("reason_code", "GROUP_MATCHING_AMBIGUOUS"))[:64]
        records: list[dict[str, object]] = []
        for side, source_ids in (
            ("Left", PostgresGroupedMatchingAdapter._record_ids(decision.get("left_record_ids", ()))),
            ("Right", PostgresGroupedMatchingAdapter._record_ids(decision.get("right_record_ids", ()))),
        ):
            for source_id in source_ids:
                records.append(
                    {
                        "exception_type": "grouped_matching_ambiguity",
                        "source_side": side,
                        "source_id": source_id,
                        "title": "Grouped matching requires review",
                        "explanation": explanation,
                        "severity": "High",
                        "risk_score": "1",
                        "reason_code": reason,
                        "owner_id": "",
                        "evidence": dict(lineage),
                    }
                )
        return tuple(records)

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
            projected_results: list[Mapping[str, object]] = []
            projected_exceptions: list[Mapping[str, object]] = []
            all_left_ids = tuple(sorted(str(item.get("id", "")) for item in request.left_records))
            all_right_ids = tuple(sorted(str(item.get("id", "")) for item in request.right_records))
            represented_left: set[str] = set()
            represented_right: set[str] = set()
            for decision in output.results:
                if not isinstance(decision, Mapping):
                    raise PostgresGroupedMatchingAdapterError("Grouped PostgreSQL strategy returned an invalid decision.")
                normalized_decision = dict(decision)
                if self._status(normalized_decision.get("status")) != "Matched":
                    if not self._record_ids(normalized_decision.get("left_record_ids", ())):
                        normalized_decision["left_record_ids"] = all_left_ids
                    if not self._record_ids(normalized_decision.get("right_record_ids", ())):
                        normalized_decision["right_record_ids"] = all_right_ids
                represented_left.update(self._record_ids(normalized_decision.get("left_record_ids", ())))
                represented_right.update(self._record_ids(normalized_decision.get("right_record_ids", ())))
                lineage = self._decision_lineage(normalized_decision, partition_key=partition.partition_key, output=output)
                projected_results.extend(self._decision_records(normalized_decision, lineage=lineage))
                projected_exceptions.extend(self._decision_exceptions(normalized_decision, lineage=lineage))
            if request.mode == "portfolio":
                missing_left = sorted(set(all_left_ids).difference(represented_left))
                missing_right = sorted(set(all_right_ids).difference(represented_right))
                portfolio_lineage = {
                    "partition_key": partition.partition_key,
                    "strategy_id": self._strategy.manifest.id,
                    "strategy_version": self._strategy.manifest.version,
                    "strategy_manifest_digest": self._strategy.manifest.digest,
                    "strategy_input_digest": output.input_digest,
                    "strategy_result_digest": output.decision_digest,
                    "explanation_schema": self._strategy.manifest.explanation_schema,
                    "reason_code": "GROUP_PORTFOLIO_UNMATCHED",
                }
                for source_id in missing_left:
                    projected_results.append(
                        {
                            "left_id": source_id,
                            "right_id": "",
                            "match_type": "grouped:portfolio",
                            "confidence": "0",
                            "explanation": "The bounded portfolio left this source record unmatched.",
                            "amount_difference": "0",
                            "date_difference_days": None,
                            "status": "Unmatched",
                            "reason_code": "GROUP_PORTFOLIO_UNMATCHED",
                            "lineage": portfolio_lineage,
                        }
                    )
                for source_id in missing_right:
                    projected_results.append(
                        {
                            "left_id": "",
                            "right_id": source_id,
                            "match_type": "grouped:portfolio",
                            "confidence": "0",
                            "explanation": "The bounded portfolio left this source record unmatched.",
                            "amount_difference": "0",
                            "date_difference_days": None,
                            "status": "Unmatched",
                            "reason_code": "GROUP_PORTFOLIO_UNMATCHED",
                            "lineage": portfolio_lineage,
                        }
                    )
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
        """Provide the non-partitioned worker contract for protocol compatibility."""

        partitions = self.iter_partition_results(context)
        return ReconciliationExecutionResult(
            results=tuple(item for partition in partitions for item in partition.results),
            exceptions=tuple(item for partition in partitions for item in partition.exceptions),
        )


__all__ = ["PostgresGroupedMatchingAdapter", "PostgresGroupedMatchingAdapterError"]
