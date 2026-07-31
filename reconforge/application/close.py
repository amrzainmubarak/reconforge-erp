"""Backend-neutral close-management application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class CloseReadiness:
    """Computed readiness without a persistence dependency."""

    period_id: str
    period_name: str
    total_tasks: int
    complete_tasks: int
    blocked_tasks: int
    readiness_score: Decimal


class CloseManagementRepositoryProtocol(Protocol):
    """Complete persistence and policy port for close-management use cases."""

    def period_init(
        self,
        *,
        period_name: str,
        start_date: str,
        end_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
        with_default_tasks: bool = True,
    ) -> dict[str, Any]: ...

    def task_add(
        self,
        *,
        period_id: str,
        task_code: str,
        name: str,
        owner: str = "",
        category: str = "",
        risk_rating: str = "medium",
        due_date: str = "",
        actor_label: str = "local-cli",
        audit_task: bool = True,
        autocommit: bool = True,
    ) -> dict[str, Any]: ...

    def task_dependency(
        self,
        *,
        task_id: str,
        depends_on_task_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def task_status(
        self,
        *,
        task_id: str,
        status: str,
        actor_label: str = "local-cli",
        blocker_reason: str = "",
    ) -> dict[str, Any]: ...

    def readiness(
        self,
        *,
        period_id: str,
        actor_label: str = "local-cli",
        audit_read: bool = True,
        autocommit: bool = True,
    ) -> CloseReadiness: ...

    def lock_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def reopen_period(self, period_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_periods(self) -> list[dict[str, Any]]: ...

    def list_tasks(self, *, period_id: str = "", status: str = "", owner: str = "") -> list[dict[str, Any]]: ...

    def get_period(self, period_id: str) -> dict[str, Any]: ...

    def get_task(self, task_id: str) -> dict[str, Any]: ...


class CloseManagementApplicationService:
    """Coordinate close workflows without importing a database adapter."""

    def __init__(self, repository: CloseManagementRepositoryProtocol) -> None:
        self.repository = repository

    def period_init(
        self,
        *,
        period_name: str,
        start_date: str,
        end_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
        with_default_tasks: bool = True,
    ) -> dict[str, Any]:
        return self.repository.period_init(
            period_name=period_name,
            start_date=start_date,
            end_date=end_date,
            workspace=workspace,
            actor_label=actor_label,
            with_default_tasks=with_default_tasks,
        )

    def task_add(
        self,
        *,
        period_id: str,
        task_code: str,
        name: str,
        owner: str = "",
        category: str = "",
        risk_rating: str = "medium",
        due_date: str = "",
        actor_label: str = "local-cli",
        audit_task: bool = True,
        autocommit: bool = True,
    ) -> dict[str, Any]:
        return self.repository.task_add(
            period_id=period_id,
            task_code=task_code,
            name=name,
            owner=owner,
            category=category,
            risk_rating=risk_rating,
            due_date=due_date,
            actor_label=actor_label,
            audit_task=audit_task,
            autocommit=autocommit,
        )

    def task_dependency(
        self,
        *,
        task_id: str,
        depends_on_task_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.task_dependency(
            task_id=task_id, depends_on_task_id=depends_on_task_id, actor_label=actor_label
        )

    def task_status(
        self,
        *,
        task_id: str,
        status: str,
        actor_label: str = "local-cli",
        blocker_reason: str = "",
    ) -> dict[str, Any]:
        return self.repository.task_status(
            task_id=task_id, status=status, actor_label=actor_label, blocker_reason=blocker_reason
        )

    def readiness(
        self,
        *,
        period_id: str,
        actor_label: str = "local-cli",
        audit_read: bool = True,
        autocommit: bool = True,
    ) -> CloseReadiness:
        return self.repository.readiness(
            period_id=period_id,
            actor_label=actor_label,
            audit_read=audit_read,
            autocommit=autocommit,
        )

    def lock_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.lock_period(period_id, actor_label=actor_label)

    def reopen_period(self, period_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.reopen_period(period_id, reason=reason, actor_label=actor_label)

    def list_periods(self) -> list[dict[str, Any]]:
        return self.repository.list_periods()

    def list_tasks(self, *, period_id: str = "", status: str = "", owner: str = "") -> list[dict[str, Any]]:
        return self.repository.list_tasks(period_id=period_id, status=status, owner=owner)

    def get_period(self, period_id: str) -> dict[str, Any]:
        return self.repository.get_period(period_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self.repository.get_task(task_id)
