"""Backend-neutral persistence boundary for non-posting deferred-tax evidence."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.consolidation_deferred_tax import (
    AcquisitionDeferredTaxBridgeRequest,
    AcquisitionDeferredTaxBridgeResult,
    prepare_acquisition_deferred_tax_bridge,
)


class AcquisitionDeferredTaxRepositoryProtocol(Protocol):
    """Persist and replay a verified, non-posting deferred-tax artifact."""

    def persist(
        self,
        request: AcquisitionDeferredTaxBridgeRequest,
        result: AcquisitionDeferredTaxBridgeResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...


class AcquisitionDeferredTaxApplicationService:
    """Prepare once, then persist only the verified non-posting artifact."""

    def __init__(self, repository: AcquisitionDeferredTaxRepositoryProtocol) -> None:
        self.repository = repository

    def prepare_and_persist(
        self,
        request: AcquisitionDeferredTaxBridgeRequest,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        result = prepare_acquisition_deferred_tax_bridge(request)
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def persist(
        self,
        request: AcquisitionDeferredTaxBridgeRequest,
        result: AcquisitionDeferredTaxBridgeResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get(artifact_id, actor_label=actor_label)


__all__ = ["AcquisitionDeferredTaxApplicationService", "AcquisitionDeferredTaxRepositoryProtocol"]
