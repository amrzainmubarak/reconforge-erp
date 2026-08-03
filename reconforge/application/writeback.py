"""Backend-neutral governed write-back intent use case boundary."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.connectors.writeback import WritebackIntent


class WritebackIntentRepositoryProtocol(Protocol):
    """Persist immutable, digest-bound write-back intent versions."""

    def put(self, intent: WritebackIntent, *, expected_version: int | None = None) -> WritebackIntent: ...

    def get(self, *, intent_id: str, tenant_id: str, workspace_id: str) -> dict[str, Any] | None: ...

    def list_latest(self, *, tenant_id: str, workspace_id: str) -> tuple[WritebackIntent, ...]: ...


class WritebackIntentApplicationService:
    """Expose the governed lifecycle without binding callers to a database."""

    def __init__(self, repository: WritebackIntentRepositoryProtocol) -> None:
        self.repository = repository

    def put(self, intent: WritebackIntent, *, expected_version: int | None = None) -> WritebackIntent:
        return self.repository.put(intent, expected_version=expected_version)

    def get(self, *, intent_id: str, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        return self.repository.get(intent_id=intent_id, tenant_id=tenant_id, workspace_id=workspace_id)

    def list_latest(self, *, tenant_id: str, workspace_id: str) -> tuple[WritebackIntent, ...]:
        return self.repository.list_latest(tenant_id=tenant_id, workspace_id=workspace_id)


__all__ = ["WritebackIntentApplicationService", "WritebackIntentRepositoryProtocol"]
