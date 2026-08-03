"""Backend-neutral application boundary for governed consolidation close state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from reconforge.domain.consolidation import ConsolidationTranslationResult
from reconforge.domain.consolidation_lifecycle import ConsolidationWorksheetResult


@dataclass(frozen=True)
class ConsolidationCloseSummary:
    """Bounded persisted lifecycle counts for one workspace."""

    workspace: str
    periods: int
    locked_periods: int
    prepared_runs: int
    approved_runs: int
    posted_runs: int
    reversal_prepared_runs: int
    reversed_runs: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ConsolidationTranslationEvidence:
    """Replay-bound FX lineage summary exposed with every close run.

    The worksheet already stores the complete translation result.  This
    projection makes the financial control evidence explicit for API/adapter
    consumers without duplicating the calculation or introducing a second
    source of truth.
    """

    schema_version: int
    algorithm_version: str
    result_digest: str
    lineage_digest: str
    line_count: int
    source_currencies: tuple[str, ...]
    rate_ids: tuple[str, ...]
    rate_types: tuple[str, ...]
    reporting_currency: str
    pre_adjustment_balance: dict[str, object]
    translation_adjustment: dict[str, object]
    post_adjustment_balance: dict[str, object]
    unrounded_translation_difference: str
    rounding_delta: str

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "line_count": self.line_count,
            "lineage_digest": self.lineage_digest,
            "post_adjustment_balance": dict(self.post_adjustment_balance),
            "pre_adjustment_balance": dict(self.pre_adjustment_balance),
            "rate_ids": list(self.rate_ids),
            "rate_types": list(self.rate_types),
            "reporting_currency": self.reporting_currency,
            "result_digest": self.result_digest,
            "rounding_delta": self.rounding_delta,
            "schema_version": self.schema_version,
            "source_currencies": list(self.source_currencies),
            "translation_adjustment": dict(self.translation_adjustment),
            "unrounded_translation_difference": self.unrounded_translation_difference,
        }


def build_translation_evidence(result: ConsolidationTranslationResult) -> ConsolidationTranslationEvidence:
    """Build a deterministic, read-only FX lineage projection from a verified result."""

    if not isinstance(result, ConsolidationTranslationResult):
        raise TypeError("A verified consolidation translation result is required.")
    line_payload = [line.to_dict() for line in result.lines]
    encoded = json.dumps(line_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    lineage_digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    return ConsolidationTranslationEvidence(
        schema_version=result.schema_version,
        algorithm_version=result.algorithm_version,
        result_digest=result.result_digest,
        lineage_digest=lineage_digest,
        line_count=len(result.lines),
        source_currencies=tuple(sorted({line.original_amount.currency for line in result.lines})),
        rate_ids=tuple(sorted({line.rate_id for line in result.lines})),
        rate_types=tuple(sorted({line.rate_type for line in result.lines})),
        reporting_currency=result.reporting_currency,
        pre_adjustment_balance=result.pre_adjustment_balance.to_canonical_dict(),
        translation_adjustment=result.translation_adjustment.to_dict(),
        post_adjustment_balance=result.post_adjustment_balance.to_canonical_dict(),
        unrounded_translation_difference=str(result.unrounded_translation_difference),
        rounding_delta=str(result.rounding_delta),
    )


class ConsolidationCloseRepositoryProtocol(Protocol):
    """Persistence port; implementations own authorization and transactions."""

    def create_period(
        self,
        *,
        group_code: str,
        period_id: str,
        reporting_currency: str,
        period_start_date: str,
        period_end_date: str,
        reporting_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def prepare_run(
        self,
        *,
        run_number: str,
        worksheet: ConsolidationWorksheetResult,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def approve_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def post_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def request_reversal(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def approve_reversal(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def prepare_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def review_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def get_certification(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def lock_period(
        self,
        period_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def reopen_period(
        self,
        period_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def get_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_periods(
        self,
        *,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def get_run(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_runs(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def summary(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> ConsolidationCloseSummary: ...


class ConsolidationCloseApplicationService:
    """Coordinate governed consolidation state without importing a database."""

    def __init__(self, repository: ConsolidationCloseRepositoryProtocol) -> None:
        self.repository = repository

    def create_period(
        self,
        *,
        group_code: str,
        period_id: str,
        reporting_currency: str,
        period_start_date: str,
        period_end_date: str,
        reporting_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_period(
            group_code=group_code,
            period_id=period_id,
            reporting_currency=reporting_currency,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            reporting_date=reporting_date,
            workspace=workspace,
            actor_label=actor_label,
        )

    def prepare_run(
        self,
        *,
        run_number: str,
        worksheet: ConsolidationWorksheetResult,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.prepare_run(
            run_number=run_number,
            worksheet=worksheet,
            workspace=workspace,
            actor_label=actor_label,
        )

    def approve_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.approve_run(
            run_id,
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
        )

    def post_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.post_run(
            run_id,
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
        )

    def request_reversal(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.request_reversal(
            run_id,
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
        )

    def approve_reversal(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.approve_reversal(
            run_id,
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
        )

    def prepare_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.prepare_certification(run_id, note=note, actor_label=actor_label)

    def review_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.review_certification(run_id, note=note, actor_label=actor_label)

    def get_certification(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_certification(run_id, actor_label=actor_label)

    def lock_period(
        self,
        period_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.lock_period(
            period_id,
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
        )

    def reopen_period(
        self,
        period_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.reopen_period(
            period_id,
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
        )

    def get_period(
        self,
        period_id: str,
        *,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.get_period(period_id, actor_label=actor_label)

    def list_periods(
        self,
        *,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_periods(
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def get_run(
        self,
        run_id: str,
        *,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.get_run(run_id, actor_label=actor_label)

    def list_runs(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_runs(
            workspace=workspace,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def summary(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> ConsolidationCloseSummary:
        return self.repository.summary(workspace=workspace, actor_label=actor_label)
