"""Backend-neutral persistence boundary for non-posting ownership-change evidence."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.consolidation_ownership_changes import (
    OwnershipChangeAdjustmentRequest,
    OwnershipChangeAdjustmentResult,
    prepare_ownership_change_adjustment,
)


class OwnershipChangeRepositoryProtocol(Protocol):
    """Persist and replay a verified, non-posting ownership-change artifact."""

    def persist(
        self,
        request: OwnershipChangeAdjustmentRequest,
        result: OwnershipChangeAdjustmentResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...


class OwnershipChangeApplicationService:
    """Prepare once, then persist only the verified non-posting artifact."""

    def __init__(self, repository: OwnershipChangeRepositoryProtocol) -> None:
        self.repository = repository

    def prepare_and_persist(
        self,
        request: OwnershipChangeAdjustmentRequest,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        result = prepare_ownership_change_adjustment(request)
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def persist(
        self,
        request: OwnershipChangeAdjustmentRequest,
        result: OwnershipChangeAdjustmentResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get(artifact_id, actor_label=actor_label)


__all__ = ["OwnershipChangeApplicationService", "OwnershipChangeRepositoryProtocol"]
