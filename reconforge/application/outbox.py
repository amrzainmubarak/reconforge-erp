"""Transactional outbox domain models and backend-neutral application service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class OutboxError(ValueError):
    """Raised for safe outbox delivery errors."""


@dataclass(frozen=True)
class OutboxEvent:
    """Immutable event snapshot handed to a publisher."""

    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload_json: str
    created_at: str
    published_at: str | None
    attempts: int
    last_error: str | None
    available_at: str | None
    locked_at: str | None
    locked_by: str | None
    dead_lettered_at: str | None


class OutboxPublisher(Protocol):
    """Injected event sink; transport concerns stay outside the local outbox."""

    def publish(self, event: OutboxEvent) -> None:
        """Publish one event or raise an exception that can be retried."""


@dataclass(frozen=True)
class OutboxProcessResult:
    """Counts from one bounded publisher pass."""

    claimed: int
    published: int
    failed: int
    dead_lettered: int


class OutboxRepositoryProtocol(Protocol):
    """Protocol for transactional outbox persistence operations."""

    def claim_pending(
        self, *, worker_id: str, limit: int = 50, max_attempts: int = 5, lease_seconds: int = 300
    ) -> list[OutboxEvent]:
        """Claim ready events with an expiring lease."""
        ...

    def mark_published(self, *, event_id: str, worker_id: str) -> None:
        """Mark a leased event published."""
        ...

    def mark_failed(
        self, *, event_id: str, worker_id: str, error: str, max_attempts: int = 5, retry_base_seconds: int = 5
    ) -> bool:
        """Record a failure and return whether the event entered dead-letter state."""
        ...

    def requeue_dead_letter(self, *, event_id: str) -> None:
        """Reset one dead-lettered event for explicit operator replay."""
        ...

    def list_events(self, *, status: str = "pending", limit: int = 100) -> list[OutboxEvent]:
        """List events by delivery status."""
        ...


class OutboxApplicationService:
    """Backend-neutral outbox delivery orchestration."""

    def __init__(
        self,
        repository: OutboxRepositoryProtocol,
        *,
        max_attempts: int = 5,
        lease_seconds: int = 300,
        retry_base_seconds: int = 5,
    ) -> None:
        if max_attempts < 1:
            raise OutboxError("max_attempts must be at least 1.")
        if lease_seconds < 1:
            raise OutboxError("lease_seconds must be at least 1.")
        if retry_base_seconds < 0:
            raise OutboxError("retry_base_seconds cannot be negative.")
        self.repository = repository
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds

    def claim_pending(self, *, worker_id: str, limit: int = 50) -> list[OutboxEvent]:
        """Claim ready events with an expiring lease, ordered deterministically."""
        return self.repository.claim_pending(
            worker_id=worker_id,
            limit=limit,
            max_attempts=self.max_attempts,
            lease_seconds=self.lease_seconds,
        )

    def process_once(
        self, *, publisher: OutboxPublisher | Callable[[OutboxEvent], None], worker_id: str, limit: int = 50
    ) -> OutboxProcessResult:
        """Claim and attempt a bounded batch without hiding publisher failures."""
        events = self.claim_pending(worker_id=worker_id, limit=limit)
        published = 0
        failed = 0
        dead_lettered = 0
        for event in events:
            try:
                if callable(publisher):
                    publisher(event)
                else:
                    publisher.publish(event)
                self.mark_published(event_id=event.id, worker_id=worker_id)
                published += 1
            except Exception as exc:  # noqa: BLE001 - publisher failures become retry state.
                failed += 1
                if self.mark_failed(event_id=event.id, worker_id=worker_id, error=str(exc)):
                    dead_lettered += 1
        return OutboxProcessResult(
            claimed=len(events),
            published=published,
            failed=failed,
            dead_lettered=dead_lettered,
        )

    def mark_published(self, *, event_id: str, worker_id: str) -> None:
        """Mark a leased event published."""
        self.repository.mark_published(event_id=event_id, worker_id=worker_id)

    def mark_failed(self, *, event_id: str, worker_id: str, error: str) -> bool:
        """Record a bounded failure and return whether the event entered dead-letter state."""
        return self.repository.mark_failed(
            event_id=event_id,
            worker_id=worker_id,
            error=error,
            max_attempts=self.max_attempts,
            retry_base_seconds=self.retry_base_seconds,
        )

    def requeue_dead_letter(self, *, event_id: str) -> None:
        """Reset one dead-lettered event for an explicit operator replay."""
        self.repository.requeue_dead_letter(event_id=event_id)

    def list_events(self, *, status: str = "pending", limit: int = 100) -> list[OutboxEvent]:
        """List events by delivery status in stable order."""
        return self.repository.list_events(status=status, limit=limit)
