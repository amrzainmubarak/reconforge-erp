"""Application port for persisted, approved consolidation ownership masters."""

from __future__ import annotations

from typing import Protocol

from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest


class ConsolidationOwnershipRepositoryProtocol(Protocol):
    def save_interest(self, interest: ConsolidationOwnershipInterest, *, group_code: str, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]: ...

    def resolve_effective(self, *, group_code: str, reporting_date: str, workspace: str = "default", actor_label: str = "local-cli") -> tuple[ConsolidationOwnershipInterest, ...]: ...


class ConsolidationOwnershipApplicationService:
    """Keep ownership persistence behind a backend-neutral application boundary."""

    def __init__(self, repository: ConsolidationOwnershipRepositoryProtocol) -> None:
        self.repository = repository

    def save(self, interest: ConsolidationOwnershipInterest, *, group_code: str, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        return self.repository.save_interest(interest, group_code=group_code, workspace=workspace, actor_label=actor_label)

    def resolve_effective(self, *, group_code: str, reporting_date: str, workspace: str = "default", actor_label: str = "local-cli") -> tuple[ConsolidationOwnershipInterest, ...]:
        return self.repository.resolve_effective(group_code=group_code, reporting_date=reporting_date, workspace=workspace, actor_label=actor_label)
