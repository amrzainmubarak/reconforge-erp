"""Persistence contract for durable provider-status observations."""

from __future__ import annotations

from typing import Protocol

from reconforge.connectors.writeback_network import WritebackRecoveryObservationRecord


class WritebackObservationPersistenceError(RuntimeError):
    """Safe persistence failure without provider payload or secret disclosure."""


class WritebackRecoveryObservationRepository(Protocol):
    """Backend-neutral append-only observation repository contract."""

    def put(self, record: WritebackRecoveryObservationRecord) -> WritebackRecoveryObservationRecord: ...

    def get(
        self,
        *,
        observation_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> WritebackRecoveryObservationRecord | None: ...

    def list_for_intent(
        self,
        *,
        intent_id: str,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> tuple[WritebackRecoveryObservationRecord, ...]: ...


__all__ = [
    "WritebackObservationPersistenceError",
    "WritebackRecoveryObservationRepository",
]
