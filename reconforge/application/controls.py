"""Backend-neutral control testing application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ControlLibraryImportResult:
    """Control library import result without a persistence dependency."""

    source_path: Path
    imported_rows: int


class ControlTestingRepositoryProtocol(Protocol):
    """Persistence and policy port for control-testing use cases."""

    def import_library(
        self, input_path: Path | str, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> ControlLibraryImportResult: ...

    def plan_tests(
        self,
        *,
        period_name: str,
        workspace: str = "default",
        sample_size: int = 0,
        actor_label: str = "local-cli",
    ) -> int: ...

    def record_result(
        self,
        *,
        plan_id: str,
        result_status: str,
        effectiveness_status: str,
        note: str = "",
        evidence_id: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def remediation(
        self,
        *,
        source_type: str,
        source_id: str,
        action_plan: str,
        owner: str = "",
        target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def report(self) -> dict[str, Any]: ...

    def list_plans(self, *, period_name: str = "") -> list[dict[str, Any]]: ...

    def get_plan(self, plan_id: str) -> dict[str, Any]: ...


class ControlTestingApplicationService:
    """Coordinate control testing without importing a database adapter."""

    def __init__(self, repository: ControlTestingRepositoryProtocol) -> None:
        self.repository = repository

    def import_library(
        self, input_path: Path | str, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> ControlLibraryImportResult:
        return self.repository.import_library(input_path, workspace=workspace, actor_label=actor_label)

    def plan_tests(
        self,
        *,
        period_name: str,
        workspace: str = "default",
        sample_size: int = 0,
        actor_label: str = "local-cli",
    ) -> int:
        return self.repository.plan_tests(
            period_name=period_name, workspace=workspace, sample_size=sample_size, actor_label=actor_label
        )

    def record_result(
        self,
        *,
        plan_id: str,
        result_status: str,
        effectiveness_status: str,
        note: str = "",
        evidence_id: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.record_result(
            plan_id=plan_id,
            result_status=result_status,
            effectiveness_status=effectiveness_status,
            note=note,
            evidence_id=evidence_id,
            actor_label=actor_label,
        )

    def remediation(
        self,
        *,
        source_type: str,
        source_id: str,
        action_plan: str,
        owner: str = "",
        target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.remediation(
            source_type=source_type,
            source_id=source_id,
            action_plan=action_plan,
            owner=owner,
            target_date=target_date,
            actor_label=actor_label,
        )

    def report(self) -> dict[str, Any]:
        return self.repository.report()

    def list_plans(self, *, period_name: str = "") -> list[dict[str, Any]]:
        return self.repository.list_plans(period_name=period_name)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return self.repository.get_plan(plan_id)
