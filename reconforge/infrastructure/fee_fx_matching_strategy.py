"""Explicit bounded fee-aware and FX-aware matching strategy adapters.

The grouped matcher already contains the reviewed arithmetic.  These adapters
publish the two financial variants as separate, auditable strategy identities
instead of hiding them behind optional request fields on a generic mode.
"""

from __future__ import annotations

from dataclasses import replace

from reconforge.application.matching_strategies import (
    MatchingStrategyContractError,
    MatchingStrategyManifest,
    MatchingStrategyRequest,
    MatchingStrategyResult,
    StrategyLimits,
    request_digest,
    result_digest,
)
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy

_COMMON_LIMITS = StrategyLimits(
    max_left_records=64,
    max_right_records=64,
    max_candidates_per_record=25_000,
    max_total_candidate_evaluations=25_000,
    max_date_window_days=3660,
    max_left_group_cardinality=1,
    max_right_group_cardinality=1,
    max_group_search_evaluations=25_000,
)

FEE_AWARE_ONE_TO_ONE_MANIFEST = MatchingStrategyManifest(
    id="bounded-fee-aware-one-to-one",
    version="1.0.0",
    maturity="experimental",
    algorithm="bounded-grouped-one-to-one-net-fee-v1",
    supported_modes=("fee-aware",),
    deterministic_tie_break="difference-date-span-stable-record-identities-v1",
    explanation_schema="grouped-matching-explanation-v2",
    limits=_COMMON_LIMITS,
)

FX_AWARE_ONE_TO_ONE_MANIFEST = MatchingStrategyManifest(
    id="bounded-fx-aware-one-to-one",
    version="1.0.0",
    maturity="experimental",
    algorithm="bounded-grouped-one-to-one-explicit-fx-v1",
    supported_modes=("fx-aware",),
    deterministic_tie_break="difference-date-span-stable-record-identities-v1",
    explanation_schema="grouped-matching-explanation-v2",
    limits=_COMMON_LIMITS,
)


class _FinancialAwareOneToOneStrategy:
    """Delegate arithmetic to the grouped implementation with strict preconditions."""

    manifest: MatchingStrategyManifest
    _kind: str

    def __init__(self) -> None:
        self._delegate = GroupedSubsetSumStrategy()

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult:
        self._validate(request)
        delegate_request = replace(
            request,
            mode="one-to-one",
            netting_mode="net" if self._kind == "fee" else request.netting_mode,
        )
        delegated = self._delegate.execute(delegate_request)
        manifest_digest = self.manifest.digest
        input_digest = request_digest(request, manifest_digest)
        result = MatchingStrategyResult(
            strategy_id=self.manifest.id,
            strategy_version=self.manifest.version,
            manifest_digest=manifest_digest,
            input_digest=input_digest,
            decision_digest=result_digest(
                manifest_digest=manifest_digest,
                input_digest=input_digest,
                results=delegated.results,
                exceptions=delegated.exceptions,
            ),
            results=delegated.results,
            exceptions=delegated.exceptions,
            explanation_schema=self.manifest.explanation_schema,
        )
        result.verify_against(
            request,
            manifest_digest=manifest_digest,
            strategy_id=self.manifest.id,
            strategy_version=self.manifest.version,
        )
        return result

    def _validate(self, request: MatchingStrategyRequest) -> None:
        if request.mode != self.manifest.supported_modes[0]:
            raise MatchingStrategyContractError("Financial-aware strategy mode is not supported.")
        if request.grouped_budget is not None:
            # The public mode is one-to-one and the adapter has its own reviewed
            # ceilings; callers may still lower those ceilings explicitly.
            request.grouped_budget.validate_against(self.manifest.limits, mode="one-to-one")
        if self._kind == "fee":
            if not request.left_fee_field.strip() or not request.right_fee_field.strip():
                raise MatchingStrategyContractError("Fee-aware strategy requires fee field names.")
            if request.netting_mode != "gross":
                raise MatchingStrategyContractError("Fee-aware strategy controls netting mode explicitly.")
        else:
            if not request.target_currency.strip():
                raise MatchingStrategyContractError("FX-aware strategy requires a target currency.")
            if not request.fx_rates:
                raise MatchingStrategyContractError("FX-aware strategy requires explicit FX rates.")


class FeeAwareOneToOneStrategy(_FinancialAwareOneToOneStrategy):
    manifest = FEE_AWARE_ONE_TO_ONE_MANIFEST
    _kind = "fee"


class FxAwareOneToOneStrategy(_FinancialAwareOneToOneStrategy):
    manifest = FX_AWARE_ONE_TO_ONE_MANIFEST
    _kind = "fx"
