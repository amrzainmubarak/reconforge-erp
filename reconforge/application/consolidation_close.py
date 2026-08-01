"""Backend-neutral application boundary for governed consolidation close state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

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
