"""Strategy-contract adapter for bounded grouped subset-sum matching."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from reconforge.application.grouped_matching import (
    GroupedMatchingApplicationService,
    GroupedMatchRequest,
)
from reconforge.application.matching_strategies import (
    MatchingStrategyContractError,
    MatchingStrategyManifest,
    MatchingStrategyRequest,
    MatchingStrategyResult,
    StrategyLimits,
    request_digest,
    result_digest,
)
from reconforge.domain.grouped_matching import GroupedMatchingError, GroupedMatchPolicy

GROUPED_SUBSET_SUM_MANIFEST = MatchingStrategyManifest(
    id="bounded-grouped-subset-sum",
    version="1.0.0",
    maturity="experimental",
    algorithm="bounded-partitioned-subset-sum-enumeration-v1",
    supported_modes=("many-to-many", "many-to-one", "one-to-many"),
    deterministic_tie_break="difference-cardinality-date-span-stable-record-identities-v1",
    explanation_schema="grouped-matching-explanation-v2",
    limits=StrategyLimits(
        max_left_records=64,
        max_right_records=64,
        max_candidates_per_record=25_000,
        max_total_candidate_evaluations=25_000,
        max_date_window_days=3660,
        max_left_group_cardinality=4,
        max_right_group_cardinality=4,
        max_group_search_evaluations=25_000,
    ),
)


class GroupedSubsetSumStrategy:
    """Execute true one/many and many/many groups under published ceilings."""

    def __init__(self) -> None:
        self._service = GroupedMatchingApplicationService()

    @property
    def manifest(self) -> MatchingStrategyManifest:
        return GROUPED_SUBSET_SUM_MANIFEST

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult:
        tolerance = self._validate_request(request)
        limits = self.manifest.limits
        group_limits = (
            limits.max_left_group_cardinality,
            limits.max_right_group_cardinality,
            limits.max_group_search_evaluations,
        )
        if any(value is None for value in group_limits):
            raise MatchingStrategyContractError("Grouped strategy manifest limits are incomplete.")
        max_left_group, max_right_group, max_group_evaluations = group_limits
        if max_left_group is None or max_right_group is None or max_group_evaluations is None:
            raise MatchingStrategyContractError("Grouped strategy manifest limits are incomplete.")
        try:
            decision = self._service.execute(
                GroupedMatchRequest(
                    left_records=request.left_records,
                    right_records=request.right_records,
                    policy=GroupedMatchPolicy(
                        mode=request.mode,  # type: ignore[arg-type]
                        amount_tolerance=tolerance,
                        date_window_days=request.date_window_days,
                        max_left_cardinality=max_left_group,
                        max_right_cardinality=max_right_group,
                        max_search_evaluations=max_group_evaluations,
                        netting_mode=request.netting_mode,
                    ),
                    left_id_field=request.left_id_field,
                    right_id_field=request.right_id_field,
                    amount_field=request.amount_field,
                    left_fee_field=request.left_fee_field,
                    right_fee_field=request.right_fee_field,
                    currency_field=request.currency_field,
                    date_field=request.date_field,
                    partition_field=request.partition_field,
                    target_currency=request.target_currency,
                    fx_rates=request.fx_rates,
                )
            )
        except GroupedMatchingError as exc:
            raise MatchingStrategyContractError(str(exc)) from exc
        payload = asdict(decision)
        results = (payload,)
        exceptions = (
            ({"reason_code": decision.reason_code, "decision_digest": decision.decision_digest},)
            if decision.status == "ambiguous"
            else ()
        )
        manifest_digest = self.manifest.digest
        input_digest = request_digest(request, manifest_digest)
        return MatchingStrategyResult(
            manifest_digest=manifest_digest,
            input_digest=input_digest,
            decision_digest=result_digest(
                manifest_digest=manifest_digest,
                input_digest=input_digest,
                results=results,
                exceptions=exceptions,
            ),
            results=results,
            exceptions=exceptions,
            explanation_schema=self.manifest.explanation_schema,
        )

    def _validate_request(self, request: MatchingStrategyRequest) -> Decimal:
        limits = self.manifest.limits
        if request.mode not in self.manifest.supported_modes:
            raise MatchingStrategyContractError("Grouped strategy mode is not supported.")
        if not isinstance(request.target_currency, str):
            raise MatchingStrategyContractError("Grouped strategy target currency must be a text value.")
        if request.target_currency and not request.target_currency.strip():
            raise MatchingStrategyContractError("Grouped strategy target currency cannot be empty text.")
        if request.fx_rates and not isinstance(request.fx_rates, tuple):
            raise MatchingStrategyContractError("Grouped strategy fx_rates must be a finite tuple of records.")
        if len(request.left_records) > limits.max_left_records or len(request.right_records) > limits.max_right_records:
            raise MatchingStrategyContractError("Grouped strategy input record limit exceeded.")
        if (
            isinstance(request.date_window_days, bool)
            or request.date_window_days < 0
            or request.date_window_days > limits.max_date_window_days
        ):
            raise MatchingStrategyContractError("Grouped strategy date-window limit exceeded.")
        if not request.amount_tolerance or len(request.amount_tolerance) > limits.max_amount_text_characters:
            raise MatchingStrategyContractError("Grouped strategy amount tolerance is invalid.")
        try:
            tolerance = Decimal(request.amount_tolerance)
        except InvalidOperation as exc:
            raise MatchingStrategyContractError("Grouped strategy amount tolerance is invalid.") from exc
        if not tolerance.is_finite() or tolerance < 0:
            raise MatchingStrategyContractError("Grouped strategy amount tolerance is invalid.")
        if request.netting_mode not in {"gross", "net"}:
            raise MatchingStrategyContractError("Grouped strategy netting mode is invalid.")
        if request.netting_mode != "gross" and (
            request.left_fee_field.strip() == "" or request.right_fee_field.strip() == ""
        ):
            raise MatchingStrategyContractError("Grouped strategy requires fee field names when netting mode is net.")
        return tolerance
