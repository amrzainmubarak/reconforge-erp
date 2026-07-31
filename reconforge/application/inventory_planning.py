"""Backend-neutral application boundary for inventory planning and counts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class InventoryPlanningSummary:
    workspace: str
    count_sessions: int
    counting_sessions: int
    submitted_sessions: int
    approved_sessions: int
    reorder_rules: int
    active_reorder_rules: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class InventoryPlanningRepositoryProtocol(Protocol):
    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryPlanningSummary: ...
    def create_count_session(
        self,
        *,
        count_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        warehouse_code: str,
        location_code: str,
        count_date: str,
        description: str = "Inventory count",
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def start_count_session(self, session_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def record_counted_quantity(
        self, session_id: str, line_id: str, *, counted_quantity: object, note: str = "", actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def submit_count_session(
        self, session_id: str, *, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def approve_count_session(
        self, session_id: str, *, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def cancel_count_session(
        self, session_id: str, *, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def get_count_session(self, session_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def list_count_sessions(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def upsert_reorder_rule(
        self,
        *,
        organization_code: str,
        entity_code: str,
        item_code: str,
        warehouse_code: str,
        location_code: str,
        minimum_quantity: object,
        target_quantity: object,
        lead_time_days: int = 0,
        active: bool = True,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def list_reorder_rules(
        self,
        *,
        workspace: str = "default",
        active_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def reorder_signals(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> dict[str, object]: ...
    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]: ...


class InventoryPlanningApplicationService:
    def __init__(self, repository: InventoryPlanningRepositoryProtocol) -> None:
        self.repository = repository

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryPlanningSummary:
        return self.repository.summary(workspace=workspace, actor_label=actor_label)

    def create_count_session(
        self,
        *,
        count_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        warehouse_code: str,
        location_code: str,
        count_date: str,
        description: str = "Inventory count",
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_count_session(
            count_number=count_number,
            organization_code=organization_code,
            entity_code=entity_code,
            period_id=period_id,
            warehouse_code=warehouse_code,
            location_code=location_code,
            count_date=count_date,
            description=description,
            workspace=workspace,
            actor_label=actor_label,
        )

    def start_count_session(self, session_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.start_count_session(session_id, actor_label=actor_label)

    def record_counted_quantity(
        self, session_id: str, line_id: str, *, counted_quantity: object, note: str = "", actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self.repository.record_counted_quantity(
            session_id, line_id, counted_quantity=counted_quantity, note=note, actor_label=actor_label
        )

    def submit_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.submit_count_session(session_id, reason=reason, actor_label=actor_label)

    def approve_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.approve_count_session(session_id, reason=reason, actor_label=actor_label)

    def cancel_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.cancel_count_session(session_id, reason=reason, actor_label=actor_label)

    def get_count_session(self, session_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_count_session(session_id, actor_label=actor_label)

    def list_count_sessions(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_count_sessions(
            workspace=workspace, status=status, limit=limit, offset=offset, actor_label=actor_label
        )

    def upsert_reorder_rule(
        self,
        *,
        organization_code: str,
        entity_code: str,
        item_code: str,
        warehouse_code: str,
        location_code: str,
        minimum_quantity: object,
        target_quantity: object,
        lead_time_days: int = 0,
        active: bool = True,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_reorder_rule(
            organization_code=organization_code,
            entity_code=entity_code,
            item_code=item_code,
            warehouse_code=warehouse_code,
            location_code=location_code,
            minimum_quantity=minimum_quantity,
            target_quantity=target_quantity,
            lead_time_days=lead_time_days,
            active=active,
            workspace=workspace,
            actor_label=actor_label,
        )

    def list_reorder_rules(
        self,
        *,
        workspace: str = "default",
        active_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_reorder_rules(
            workspace=workspace, active_only=active_only, limit=limit, offset=offset, actor_label=actor_label
        )

    def reorder_signals(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        return self.repository.reorder_signals(
            organization_code=organization_code,
            entity_code=entity_code,
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        return self.repository.snapshot(workspace=workspace, actor_label=actor_label)
