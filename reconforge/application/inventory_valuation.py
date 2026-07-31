"""Backend-neutral application boundary for governed inventory valuation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class InventoryValuationSummary:
    """Bounded control counts for the inventory valuation foundation."""

    workspace: str
    policies: int
    draft_documents: int
    approved_documents: int
    open_layers: int
    unvalued_posted_movements: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class InventoryValuationRepositoryProtocol(Protocol):
    """Complete use-case port; implementations own persistence and transactions."""

    def upsert_policy(
        self,
        *,
        policy_code: str,
        organization_code: str,
        entity_code: str,
        journal_code: str,
        receipt_clearing_account_code: str,
        cogs_account_code: str,
        adjustment_account_code: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def create_document(
        self,
        *,
        valuation_number: str,
        movement_id: str,
        policy_code: str,
        input_costs: Sequence[Mapping[str, object]] = (),
        valuation_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def approve_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def cancel_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def get_policy(self, policy_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_policies(
        self,
        *,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def get_document(self, document_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_documents(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def list_cost_layers(
        self,
        *,
        workspace: str = "default",
        open_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryValuationSummary: ...

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]: ...


class InventoryValuationApplicationService:
    """Coordinate valuation use cases without a database dependency."""

    def __init__(self, repository: InventoryValuationRepositoryProtocol) -> None:
        self.repository = repository

    def upsert_policy(
        self,
        *,
        policy_code: str,
        organization_code: str,
        entity_code: str,
        journal_code: str,
        receipt_clearing_account_code: str,
        cogs_account_code: str,
        adjustment_account_code: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_policy(
            policy_code=policy_code,
            organization_code=organization_code,
            entity_code=entity_code,
            journal_code=journal_code,
            receipt_clearing_account_code=receipt_clearing_account_code,
            cogs_account_code=cogs_account_code,
            adjustment_account_code=adjustment_account_code,
            workspace=workspace,
            active=active,
            actor_label=actor_label,
        )

    def create_document(
        self,
        *,
        valuation_number: str,
        movement_id: str,
        policy_code: str,
        input_costs: Sequence[Mapping[str, object]] = (),
        valuation_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_document(
            valuation_number=valuation_number,
            movement_id=movement_id,
            policy_code=policy_code,
            input_costs=input_costs,
            valuation_date=valuation_date,
            actor_label=actor_label,
        )

    def approve_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.approve_document(document_id, reason=reason, actor_label=actor_label)

    def cancel_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.cancel_document(document_id, reason=reason, actor_label=actor_label)

    def get_policy(self, policy_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_policy(policy_id, actor_label=actor_label)

    def list_policies(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        return self.repository.list_policies(workspace=workspace, limit=limit, offset=offset, actor_label=actor_label)

    def get_document(self, document_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_document(document_id, actor_label=actor_label)

    def list_documents(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_documents(
            workspace=workspace, status=status, limit=limit, offset=offset, actor_label=actor_label
        )

    def list_cost_layers(
        self,
        *,
        workspace: str = "default",
        open_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_cost_layers(
            workspace=workspace, open_only=open_only, limit=limit, offset=offset, actor_label=actor_label
        )

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryValuationSummary:
        return self.repository.summary(workspace=workspace, actor_label=actor_label)

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.snapshot(workspace=workspace, actor_label=actor_label)
