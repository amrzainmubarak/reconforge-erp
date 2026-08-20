"""Strategy adapter for bounded reversal pairing."""

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
from reconforge.domain.reversal_matching import (
    ReversalMatchingError,
    ReversalMatchingPolicy,
    ReversalRecord,
    pair_reversals,
)

REVERSAL_PAIRING_MANIFEST = MatchingStrategyManifest(
    id="bounded-reversal-pairing",
    version="1.0.0",
    maturity="experimental",
    algorithm="partitioned-opposite-sign-date-window-reversal-pairing-v1",
    supported_modes=("reversal-pairing",),
    deterministic_tie_break="explicit-link-amount-difference-date-span-stable-record-identities-v1",
    explanation_schema="reversal-matching-explanation-v1",
    limits=StrategyLimits(
        max_left_records=250_000,
        max_right_records=250_000,
        max_candidates_per_record=10_000,
        max_total_candidate_evaluations=25_000,
        max_date_window_days=3660,
    ),
)


class ReversalPairingStrategy:
    @property
    def manifest(self) -> MatchingStrategyManifest:
        return REVERSAL_PAIRING_MANIFEST

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult:
        reject_unsupported_grouped_budget(request, strategy_name="Reversal strategy")
        if request.mode not in self.manifest.supported_modes:
            raise MatchingStrategyContractError("Reversal strategy mode is not supported.")
        limits = self.manifest.limits
        if len(request.left_records) > limits.max_left_records or len(request.right_records) > limits.max_right_records:
            raise MatchingStrategyContractError("Reversal strategy input record limit exceeded.")
        if isinstance(request.date_window_days, bool) or not 0 <= request.date_window_days <= limits.max_date_window_days:
            raise MatchingStrategyContractError("Reversal strategy date-window limit exceeded.")
        try:
            tolerance = Decimal(request.amount_tolerance)
            originals = tuple(self._record(item, request, request.left_id_field) for item in request.left_records)
            reversals = tuple(self._record(item, request, request.right_id_field) for item in request.right_records)
            decision = pair_reversals(
                originals,
                reversals,
                ReversalMatchingPolicy(
                    date_window_days=request.date_window_days,
                    amount_tolerance=tolerance,
                    max_candidates=limits.max_candidates_per_record,
                    max_search_evaluations=limits.max_total_candidate_evaluations,
                ),
            )
        except (ReversalMatchingError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
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
    def _record(item: Mapping[str, object], request: MatchingStrategyRequest, id_field: str) -> ReversalRecord:
        try:
            return ReversalRecord(
                record_id=str(item[id_field]),
                amount=Decimal(str(item[request.amount_field])),
                currency=str(item.get(request.currency_field, "")),
                business_date=date.fromisoformat(str(item[request.date_field])),
                partition_key=str(item.get(request.partition_field, "")),
                reversal_of=str(item.get("reversal_of", "")),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise MatchingStrategyContractError("Reversal record fields are invalid.") from exc
