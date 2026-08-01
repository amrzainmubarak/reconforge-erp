"""Backend-neutral exception queue application boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


class ExceptionQueueRepositoryProtocol(Protocol):
    """Persistence and policy port for the unified exception queue."""

    def upsert_exception(
        self,
        *,
        source_type: str,
        source_id: str,
        description: str,
        workspace: str = "default",
        period_name: str = "",
        entity_code: str = "",
        account_code: str = "",
        control_code: str = "",
        risk_rating: str = "medium",
        owner: str = "",
        status: str = "Open",
        escalation_level: str = "",
        sla_target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list(
        self,
        *,
        period_name: str = "",
        entity_code: str = "",
        account_code: str = "",
        control_code: str = "",
        risk_rating: str = "",
        owner: str = "",
        status: str = "",
    ) -> list[dict[str, Any]]: ...

    def assign(self, exception_id: str, *, owner: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def set_status(self, exception_id: str, *, status: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def bulk_update(
        self,
        exception_ids: Sequence[str],
        *,
        status: str = "",
        owner: str = "",
        actor_label: str = "local-cli",
    ) -> int: ...

    def get(self, exception_id: str) -> dict[str, Any]: ...


class ExceptionQueueApplicationService:
    """Coordinate exception queue use cases without a database dependency."""

    def __init__(self, repository: ExceptionQueueRepositoryProtocol) -> None:
        self.repository = repository

    def upsert_exception(
        self,
        *,
        source_type: str,
        source_id: str,
        description: str,
        workspace: str = "default",
        period_name: str = "",
        entity_code: str = "",
        account_code: str = "",
        control_code: str = "",
        risk_rating: str = "medium",
        owner: str = "",
        status: str = "Open",
        escalation_level: str = "",
        sla_target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_exception(
            source_type=source_type,
            source_id=source_id,
            description=description,
            workspace=workspace,
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
            control_code=control_code,
            risk_rating=risk_rating,
            owner=owner,
            status=status,
            escalation_level=escalation_level,
            sla_target_date=sla_target_date,
            actor_label=actor_label,
        )

    def list(
        self,
        *,
        period_name: str = "",
        entity_code: str = "",
        account_code: str = "",
        control_code: str = "",
        risk_rating: str = "",
        owner: str = "",
        status: str = "",
    ) -> list[dict[str, Any]]:
        return self.repository.list(
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
            control_code=control_code,
            risk_rating=risk_rating,
            owner=owner,
            status=status,
        )

    def assign(self, exception_id: str, *, owner: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.assign(exception_id, owner=owner, actor_label=actor_label)

    def set_status(self, exception_id: str, *, status: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.set_status(exception_id, status=status, actor_label=actor_label)

    def bulk_update(
        self,
        exception_ids: Sequence[str],
        *,
        status: str = "",
        owner: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        return self.repository.bulk_update(exception_ids, status=status, owner=owner, actor_label=actor_label)

    def get(self, exception_id: str) -> dict[str, Any]:
        return self.repository.get(exception_id)
