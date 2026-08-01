"""Backend-neutral application boundary for governed valuation reversals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class InventoryValuationReversalSummary:
    """Bounded reversal workflow counts for one workspace."""

    workspace: str
    draft_reversals: int
    approved_reversals: int
    cancelled_reversals: int
    approved_effects: int
    finance_drafts: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class InventoryValuationReversalRepositoryProtocol(Protocol):
    """Complete reversal use-case port with adapter-owned transactions."""

    def create_reversal(
        self,
        *,
        reversal_number: str,
        original_valuation_document_id: str,
        reversal_movement_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def approve_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def cancel_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def get_reversal(self, reversal_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def list_reversals(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def summary(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> InventoryValuationReversalSummary: ...
    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]: ...


class InventoryValuationReversalApplicationService:
    """Coordinate compensating valuation use cases without database coupling."""

    def __init__(self, repository: InventoryValuationReversalRepositoryProtocol) -> None:
        self.repository = repository

    def create_reversal(
        self,
        *,
        reversal_number: str,
        original_valuation_document_id: str,
        reversal_movement_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_reversal(
            reversal_number=reversal_number,
            original_valuation_document_id=original_valuation_document_id,
            reversal_movement_id=reversal_movement_id,
            actor_label=actor_label,
        )

    def approve_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.approve_reversal(reversal_id, reason=reason, actor_label=actor_label)

    def cancel_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.cancel_reversal(reversal_id, reason=reason, actor_label=actor_label)

    def get_reversal(self, reversal_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_reversal(reversal_id, actor_label=actor_label)

    def list_reversals(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_reversals(
            workspace=workspace, status=status, limit=limit, offset=offset, actor_label=actor_label
        )

    def summary(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> InventoryValuationReversalSummary:
        return self.repository.summary(workspace=workspace, actor_label=actor_label)

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.snapshot(workspace=workspace, actor_label=actor_label)
