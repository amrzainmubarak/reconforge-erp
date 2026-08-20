"""Backend-neutral persistence boundary for non-posting impairment evidence."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.consolidation_impairment import (
    ConsolidationImpairmentBridgeRequest,
    ConsolidationImpairmentBridgeResult,
    prepare_consolidation_impairment_bridge,
)


class ConsolidationImpairmentRepositoryProtocol(Protocol):
    """Persist and replay a verified, non-posting impairment artifact."""

    def persist(
        self,
        request: ConsolidationImpairmentBridgeRequest,
        result: ConsolidationImpairmentBridgeResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...


class ConsolidationImpairmentApplicationService:
    """Prepare once, then persist only the verified non-posting artifact."""

    def __init__(self, repository: ConsolidationImpairmentRepositoryProtocol) -> None:
        self.repository = repository

    def prepare_and_persist(
        self,
        request: ConsolidationImpairmentBridgeRequest,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        result = prepare_consolidation_impairment_bridge(request)
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def persist(
        self,
        request: ConsolidationImpairmentBridgeRequest,
        result: ConsolidationImpairmentBridgeResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get(artifact_id, actor_label=actor_label)


__all__ = ["ConsolidationImpairmentApplicationService", "ConsolidationImpairmentRepositoryProtocol"]
