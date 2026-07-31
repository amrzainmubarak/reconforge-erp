"""Backend-neutral deterministic matching application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
)

LEGACY_RECORD_IDENTITY_POLICY = "row-order-occurrence-legacy-v0"


@dataclass(frozen=True)
class ReferenceNormalizationRules:
    """Normalization settings for deterministic reference matching."""

    unicode_normalization: str = "NFKC"
    case: str = "upper"
    trim_whitespace: bool = True
    remove_whitespace: bool = True
    separator_normalizations: tuple[tuple[str, str], ...] = ()
    strip_prefixes: tuple[str, ...] = ()
    strip_suffixes: tuple[str, ...] = ()
    leading_zeros: bool = True
    regex_normalizations: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MatchRunResult:
    """Result from one deterministic match job."""

    job_id: str
    result_count: int
    matched_count: int
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY
    record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY


@dataclass(frozen=True)
class DeterministicMatchOutput:
    """Pure matcher output separated from persistence."""

    results: tuple[dict[str, Any], ...]
    exceptions: tuple[dict[str, Any], ...]
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY
    record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY


class CurrencyPrecisionResolver(Protocol):
    """Resolve one currency without coupling the matcher to a storage engine."""

    def __call__(self, currency_code: str) -> tuple[int | None, str | None]: ...


class DeterministicMatchingEngineProtocol(Protocol):
    """Persistence-independent governed record-matching contract."""

    def match_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | ReferenceNormalizationRules | None = None,
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
        _source_locations_trusted: bool = False,
    ) -> DeterministicMatchOutput: ...


class MatchingRepositoryProtocol(DeterministicMatchingEngineProtocol, Protocol):
    """Complete execution and persistence port extending the pure engine."""

    def run(
        self,
        *,
        left_path: Path | str,
        right_path: Path | str,
        workspace: str = "default",
        name: str = "local-match-job",
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        actor_label: str = "local-cli",
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
    ) -> MatchRunResult: ...
    def benchmark(self, *, rows: int, workspace: str = "default", actor_label: str = "local-cli") -> MatchRunResult: ...
    def job_status(self, job_id: str) -> dict[str, Any]: ...
    def results(self, job_id: str, *, status: str = "") -> list[dict[str, Any]]: ...
    def list_jobs(self) -> list[dict[str, Any]]: ...


class MatchingApplicationService:
    """Coordinate deterministic matching without importing a database adapter."""

    def __init__(self, repository: MatchingRepositoryProtocol) -> None:
        self.repository = repository

    def run(
        self,
        *,
        left_path: Path | str,
        right_path: Path | str,
        workspace: str = "default",
        name: str = "local-match-job",
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        actor_label: str = "local-cli",
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
    ) -> MatchRunResult:
        return self.repository.run(
            left_path=left_path,
            right_path=right_path,
            workspace=workspace,
            name=name,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
            reference_normalization_rules=reference_normalization_rules,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
        )

    def benchmark(self, *, rows: int, workspace: str = "default", actor_label: str = "local-cli") -> MatchRunResult:
        return self.repository.benchmark(rows=rows, workspace=workspace, actor_label=actor_label)

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self.repository.job_status(job_id)

    def results(self, job_id: str, *, status: str = "") -> list[dict[str, Any]]:
        return self.repository.results(job_id, status=status)

    def list_jobs(self) -> list[dict[str, Any]]:
        return self.repository.list_jobs()

    def match_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | ReferenceNormalizationRules | None = None,
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
        _source_locations_trusted: bool = False,
    ) -> DeterministicMatchOutput:
        return self.repository.match_records(
            left_records=left_records,
            right_records=right_records,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
            reference_normalization_rules=reference_normalization_rules,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
            _source_locations_trusted=_source_locations_trusted,
        )
