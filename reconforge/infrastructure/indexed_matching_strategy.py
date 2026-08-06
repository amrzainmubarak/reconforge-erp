"""Adapter exposing the existing indexed matcher through the strategy contract."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from reconforge.application.matching_strategies import (
    MatchingStrategyContractError,
    MatchingStrategyManifest,
    MatchingStrategyRequest,
    MatchingStrategyResult,
    StrategyLimits,
    request_digest,
    result_digest,
)
from reconforge.platform.matching import MatchingService

INDEXED_ONE_TO_ONE_MANIFEST = MatchingStrategyManifest(
    id="indexed-composite-one-to-one",
    version="1.0.0",
    maturity="beta",
    algorithm="range-indexed-candidate-generation-plus-deterministic-min-cost-assignment-v1",
    supported_modes=("amount-tolerance", "date-window", "exact-fields", "reference-normalized"),
    deterministic_tie_break="record-fingerprint-cost-right-fingerprint-left-id-right-id-v1",
    explanation_schema="matching-explanation-v1",
    limits=StrategyLimits(
        max_left_records=250_000,
        max_right_records=250_000,
        max_candidates_per_record=10_000,
        max_total_candidate_evaluations=1_000_000,
        max_date_window_days=3660,
    ),
)


class IndexedOneToOneStrategy:
    """Compatibility adapter for the current indexed one-to-one matcher."""

    def __init__(self, service: MatchingService) -> None:
        self._service = service

    @property
    def manifest(self) -> MatchingStrategyManifest:
        return INDEXED_ONE_TO_ONE_MANIFEST

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult:
        self._validate_request(request)
        output = self._service.match_records(
            left_records=[dict(record) for record in request.left_records],
            right_records=[dict(record) for record in request.right_records],
            left_id_field=request.left_id_field,
            right_id_field=request.right_id_field,
            amount_field=request.amount_field,
            date_field=request.date_field,
            reference_field=request.reference_field,
            exact_fields=request.exact_fields,
            amount_tolerance=request.amount_tolerance,
            date_window_days=request.date_window_days,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
        manifest_digest = self.manifest.digest
        input_digest = request_digest(request, manifest_digest)
        decision_digest = result_digest(
            manifest_digest=manifest_digest,
            input_digest=input_digest,
            results=output.results,
            exceptions=output.exceptions,
        )
        result = MatchingStrategyResult(
            manifest_digest=manifest_digest,
            input_digest=input_digest,
            decision_digest=decision_digest,
            results=output.results,
            exceptions=output.exceptions,
            explanation_schema=self.manifest.explanation_schema,
        )
        result.verify_against(request, manifest_digest=manifest_digest)
        return result

    def _validate_request(self, request: MatchingStrategyRequest) -> None:
        limits = self.manifest.limits
        if request.mode != "one-to-one":
            raise MatchingStrategyContractError("Indexed one-to-one strategy does not support the requested mode.")
        if len(request.left_records) > limits.max_left_records or len(request.right_records) > limits.max_right_records:
            raise MatchingStrategyContractError("Matching strategy input record limit exceeded.")
        if (
            isinstance(request.date_window_days, bool)
            or request.date_window_days < 0
            or request.date_window_days > limits.max_date_window_days
        ):
            raise MatchingStrategyContractError("Matching strategy date-window limit exceeded.")
        if not request.amount_tolerance or len(request.amount_tolerance) > limits.max_amount_text_characters:
            raise MatchingStrategyContractError("Matching strategy amount tolerance is invalid.")
        try:
            tolerance = Decimal(request.amount_tolerance)
        except InvalidOperation as exc:
            raise MatchingStrategyContractError("Matching strategy amount tolerance is invalid.") from exc
        if not tolerance.is_finite() or tolerance < 0:
            raise MatchingStrategyContractError("Matching strategy amount tolerance is invalid.")
