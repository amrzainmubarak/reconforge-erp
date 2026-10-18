"""Connection-free stock procurement use-case boundary."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.procurement_operations import ProcurementPreparation


class ProcurementRepository(Protocol):
    def create(self, request: ProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def act(self, cycle_id: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, actor: PostingActor) -> dict[str, Any]: ...
    def get(self, cycle_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list_cycles(self, workspace: str, *, actor: PostingActor) -> list[Mapping[str, Any]]: ...


class ProcurementApplicationService:
    def __init__(self, repository: ProcurementRepository) -> None:
        self.repository = repository

    def create(self, request: ProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create(request, command_id=command_id, actor=actor)

    def act(self, cycle_id: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act(cycle_id, operation, expected_version=expected_version,
            command_id=command_id, reason=reason, actor=actor)

    def get(self, cycle_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(cycle_id, actor=actor)

    def list_cycles(self, workspace: str, *, actor: PostingActor) -> list[Mapping[str, Any]]:
        return self.repository.list_cycles(workspace, actor=actor)
