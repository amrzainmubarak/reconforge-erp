"""Strategy adapter for bounded FIFO carry-forward allocation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation

from reconforge.application.matching_strategies import (
    MatchingStrategyContractError,
    MatchingStrategyManifest,
    MatchingStrategyRequest,
    MatchingStrategyResult,
    StrategyLimits,
    reject_unsupported_grouped_budget,
    request_digest,
    result_digest,
)
from reconforge.domain.carry_forward import (
    CarryForwardError,
    CarryForwardPolicy,
    CarryForwardRecord,
    allocate_carry_forward,
    allocate_sequence_window,
)

CARRY_FORWARD_FIFO_MANIFEST = MatchingStrategyManifest(
    id="bounded-carry-forward-fifo",
    version="1.0.0",
    maturity="experimental",
    algorithm="partitioned-fifo-and-contiguous-sequence-window-allocation-v2",
    supported_modes=("carry-forward", "sequence-window"),
    deterministic_tie_break="difference-cardinality-start-index-stable-record-identities-v2",
    explanation_schema="carry-forward-explanation-v1",
    limits=StrategyLimits(
        max_left_records=250_000,
        max_right_records=250_000,
        max_candidates_per_record=10_000,
        max_total_candidate_evaluations=25_000,
        max_date_window_days=3660,
        max_left_group_cardinality=16,
    ),
)


class CarryForwardFifoStrategy:
    @property
    def manifest(self) -> MatchingStrategyManifest:
        return CARRY_FORWARD_FIFO_MANIFEST

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult:
        reject_unsupported_grouped_budget(request, strategy_name="Carry-forward strategy")
        if request.mode not in self.manifest.supported_modes:
            raise MatchingStrategyContractError("Carry-forward strategy mode is not supported.")
        limits = self.manifest.limits
        if len(request.left_records) > limits.max_left_records or len(request.right_records) > limits.max_right_records:
            raise MatchingStrategyContractError("Carry-forward strategy input record limit exceeded.")
        if isinstance(request.date_window_days, bool) or not 0 <= request.date_window_days <= limits.max_date_window_days:
            raise MatchingStrategyContractError("Carry-forward strategy date-window limit exceeded.")
        try:
            obligations = tuple(self._record(item, request, request.left_id_field) for item in request.left_records)
            settlements = tuple(self._record(item, request, request.right_id_field) for item in request.right_records)
            tolerance = Decimal(str(request.amount_tolerance))
            if not tolerance.is_finite() or tolerance < 0:
                raise MatchingStrategyContractError("Carry-forward amount tolerance is invalid.")
            policy = CarryForwardPolicy(
                date_window_days=request.date_window_days,
                amount_tolerance=tolerance,
                max_search_evaluations=limits.max_total_candidate_evaluations,
                max_window_cardinality=limits.max_left_group_cardinality or 16,
            )
            if request.mode == "sequence-window":
                decision = allocate_sequence_window(obligations, settlements, policy)
            else:
                decision = allocate_carry_forward(obligations, settlements, policy)
        except (CarryForwardError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise MatchingStrategyContractError(str(exc)) from exc
        results = (asdict(decision),)
        exceptions = () if decision.status != "ambiguous" else ({"reason_code": decision.reason_code, "decision_digest": decision.decision_digest},)
        manifest_digest = self.manifest.digest
        input_digest = request_digest(request, manifest_digest)
        result = MatchingStrategyResult(
            manifest_digest=manifest_digest,
            input_digest=input_digest,
            decision_digest=result_digest(manifest_digest=manifest_digest, input_digest=input_digest, results=results, exceptions=exceptions),
            results=results,
            exceptions=exceptions,
            explanation_schema=self.manifest.explanation_schema,
        )
        result.verify_against(request, manifest_digest=manifest_digest)
        return result

    @staticmethod
    def _record(item: Mapping[str, object], request: MatchingStrategyRequest, id_field: str) -> CarryForwardRecord:
        try:
            amount = Decimal(str(item[request.amount_field]))
            record_date = date.fromisoformat(str(item[request.date_field]))
            record_id = str(item[id_field])
            currency = str(item.get(request.currency_field, ""))
            partition = str(item.get(request.partition_field, ""))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise MatchingStrategyContractError("Carry-forward record fields are invalid.") from exc
        return CarryForwardRecord(record_id, amount, currency, record_date, partition)
