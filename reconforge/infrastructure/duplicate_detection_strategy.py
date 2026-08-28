"""Strategy-contract adapter for bounded duplicate fingerprint evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

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
from reconforge.domain.duplicate_detection import (
    DuplicateDetectionError,
    DuplicateDetectionPolicy,
    detect_duplicates,
)

DUPLICATE_DETECTION_MANIFEST = MatchingStrategyManifest(
    id="bounded-duplicate-detection",
    version="1.0.0",
    maturity="experimental",
    algorithm="partitioned-canonical-fingerprint-occurrence-grouping-v1",
    supported_modes=("duplicate-detection",),
    deterministic_tie_break="fingerprint-record-id-occurrence-ordinal-v1",
    explanation_schema="duplicate-detection-explanation-v1",
    limits=StrategyLimits(
        max_left_records=250_000,
        max_right_records=250_000,
        max_candidates_per_record=1,
        max_total_candidate_evaluations=500_000,
        max_date_window_days=3660,
        max_amount_text_characters=128,
    ),
)


class DuplicateDetectionStrategy:
    """Detect exact canonical duplicates without mutating either input set."""

    @property
    def manifest(self) -> MatchingStrategyManifest:
        return DUPLICATE_DETECTION_MANIFEST

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult:
        self._validate_request(request)
        fields = self._fingerprint_fields(request)
        try:
            detection = detect_duplicates(
                request.left_records,
                request.right_records,
                fingerprint_fields=fields,
                amount_field=request.amount_field,
                left_id_field=request.left_id_field,
                right_id_field=request.right_id_field,
                policy=DuplicateDetectionPolicy(
                    max_records_per_side=self.manifest.limits.max_left_records,
                    max_total_evaluations=self.manifest.limits.max_total_candidate_evaluations,
                    max_fingerprint_fields=self.manifest.limits.max_amount_text_characters // 4,
                ),
            )
        except DuplicateDetectionError as exc:
            raise MatchingStrategyContractError(str(exc)) from exc

        results = tuple(asdict(group) for group in detection.groups)
        exceptions: tuple[Mapping[str, object], ...]
        if detection.status == "ambiguous":
            exceptions = (
                {
                    "reason_code": detection.reason_code,
                    "records_processed": detection.records_processed,
                    "fingerprint_evaluations": detection.fingerprint_evaluations,
                },
            )
        else:
            exceptions = tuple(
                {
                    "reason_code": group.reason_code,
                    "side": group.side,
                    "fingerprint": group.fingerprint,
                    "record_ids": group.record_ids,
                    "occurrence_ids": group.occurrence_ids,
                }
                for group in detection.groups
                if group.status == "duplicate"
            )
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
                results=results,
                exceptions=exceptions,
            ),
            results=results,
            exceptions=exceptions,
            explanation_schema=self.manifest.explanation_schema,
        )
        result.verify_against(request, manifest_digest=manifest_digest, strategy_id=self.manifest.id, strategy_version=self.manifest.version)
        return result

    def _validate_request(self, request: MatchingStrategyRequest) -> None:
        reject_unsupported_grouped_budget(request, strategy_name="Duplicate-detection strategy")
        if request.mode not in self.manifest.supported_modes:
            raise MatchingStrategyContractError("Duplicate-detection strategy mode is not supported.")
        if len(request.left_records) > self.manifest.limits.max_left_records or len(request.right_records) > self.manifest.limits.max_right_records:
            raise MatchingStrategyContractError("Duplicate-detection strategy input record limit exceeded.")
        if not request.amount_field.strip() or not request.left_id_field.strip() or not request.right_id_field.strip():
            raise MatchingStrategyContractError("Duplicate-detection field names cannot be empty.")

    @staticmethod
    def _fingerprint_fields(request: MatchingStrategyRequest) -> tuple[str, ...]:
        if request.exact_fields.strip():
            fields = tuple(part.strip() for part in request.exact_fields.split(","))
        else:
            fields = (
                request.amount_field,
                request.date_field,
                request.reference_field,
                request.currency_field,
                request.partition_field,
            )
        if not fields or any(not field for field in fields):
            raise MatchingStrategyContractError("Duplicate-detection fingerprint fields are invalid.")
        return fields
