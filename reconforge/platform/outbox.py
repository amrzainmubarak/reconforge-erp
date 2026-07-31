"""Transactional outbox claiming, publishing, retry, and dead-letter state."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from reconforge.application.outbox import (
    OutboxApplicationService,
    OutboxEvent,
    OutboxProcessResult,
    OutboxPublisher,
)
from reconforge.application.outbox import (
    OutboxError as OutboxError,
)
from reconforge.infrastructure.sqlite_outbox import SQLiteOutboxRepository


class OutboxService:
    """SQLite outbox service with leases and deterministic retry state."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        max_attempts: int = 5,
        lease_seconds: int = 300,
        retry_base_seconds: int = 5,
    ) -> None:
        self.connection = connection
        self.service = OutboxApplicationService(
            repository=SQLiteOutboxRepository(connection),
            max_attempts=max_attempts,
            lease_seconds=lease_seconds,
            retry_base_seconds=retry_base_seconds,
        )

    def claim_pending(self, *, worker_id: str, limit: int = 50) -> list[OutboxEvent]:
        """Claim ready events with an expiring lease, ordered deterministically."""
        return self.service.claim_pending(worker_id=worker_id, limit=limit)

    def process_once(
        self, *, publisher: OutboxPublisher | Callable[[OutboxEvent], None], worker_id: str, limit: int = 50
    ) -> OutboxProcessResult:
        """Claim and attempt a bounded batch without hiding publisher failures."""
        return self.service.process_once(publisher=publisher, worker_id=worker_id, limit=limit)

    def mark_published(self, *, event_id: str, worker_id: str) -> None:
        """Mark a leased event published only for the worker holding its lease."""
        self.service.mark_published(event_id=event_id, worker_id=worker_id)

    def mark_failed(self, *, event_id: str, worker_id: str, error: str) -> bool:
        """Record a bounded failure and return whether the event entered dead-letter state."""
        return self.service.mark_failed(event_id=event_id, worker_id=worker_id, error=error)

    def requeue_dead_letter(self, *, event_id: str) -> None:
        """Reset one dead-lettered event for an explicit operator replay."""
        self.service.requeue_dead_letter(event_id=event_id)

    def list_events(self, *, status: str = "pending", limit: int = 100) -> list[OutboxEvent]:
        """List events by delivery status in stable order."""
        return self.service.list_events(status=status, limit=limit)
