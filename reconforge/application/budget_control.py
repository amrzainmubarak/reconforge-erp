"""Backend-neutral operational appropriation and commitment use cases."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.budget_control import BudgetDefinition, BudgetScope, CommitmentAction


class BudgetControlRepository(Protocol):
    def create(self, scope: BudgetScope, definition: BudgetDefinition, *, command_id: str) -> dict[str, Any]: ...
    def transition(self, scope: BudgetScope, budget_id: str, *, action: str, expected_version: int, reason: str, command_id: str) -> dict[str, Any]: ...
    def record(self, scope: BudgetScope, budget_id: str, action: CommitmentAction, *, expected_version: int, command_id: str, commitment_id: str = "") -> dict[str, Any]: ...
    def get(self, scope: BudgetScope, budget_id: str) -> dict[str, Any]: ...
    def list(self, scope: BudgetScope, *, limit: int = 50, offset: int = 0) -> dict[str, Any]: ...


class BudgetControlService:
    """One shared financial control port for future procurement/expense callers."""

    def __init__(self, repository: BudgetControlRepository) -> None:
        self.repository = repository

    def create(self, scope: BudgetScope, definition: BudgetDefinition, *, command_id: str) -> dict[str, Any]:
        return self.repository.create(scope, definition, command_id=command_id)

    def transition(self, scope: BudgetScope, budget_id: str, *, action: str, expected_version: int, reason: str, command_id: str) -> dict[str, Any]:
        return self.repository.transition(scope, budget_id, action=action, expected_version=expected_version, reason=reason, command_id=command_id)

    def record(self, scope: BudgetScope, budget_id: str, action: CommitmentAction, *, expected_version: int, command_id: str, commitment_id: str = "") -> dict[str, Any]:
        return self.repository.record(scope, budget_id, action, expected_version=expected_version, command_id=command_id, commitment_id=commitment_id)

    def get(self, scope: BudgetScope, budget_id: str) -> dict[str, Any]:
        return self.repository.get(scope, budget_id)

    def list(self, scope: BudgetScope, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return self.repository.list(scope, limit=limit, offset=offset)
