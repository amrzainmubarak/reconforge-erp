"""Backend-neutral persistence boundary for non-posting acquisition PPA evidence."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.consolidation_ppa import (
    AcquisitionPurchasePriceAllocationRequest,
    AcquisitionPurchasePriceAllocationResult,
    prepare_acquisition_purchase_price_allocation,
)


class AcquisitionPpaRepositoryProtocol(Protocol):
    """Persist and replay a verified, non-posting PPA artifact."""

    def persist(
        self,
        request: AcquisitionPurchasePriceAllocationRequest,
        result: AcquisitionPurchasePriceAllocationResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...


class AcquisitionPpaApplicationService:
    """Prepare once, then persist only the verified non-posting artifact."""

    def __init__(self, repository: AcquisitionPpaRepositoryProtocol) -> None:
        self.repository = repository

    def prepare_and_persist(
        self,
        request: AcquisitionPurchasePriceAllocationRequest,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        result = prepare_acquisition_purchase_price_allocation(request)
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def persist(
        self,
        request: AcquisitionPurchasePriceAllocationRequest,
        result: AcquisitionPurchasePriceAllocationResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.persist(request, result, artifact_id=artifact_id, actor_label=actor_label)

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get(artifact_id, actor_label=actor_label)


__all__ = ["AcquisitionPpaApplicationService", "AcquisitionPpaRepositoryProtocol"]
