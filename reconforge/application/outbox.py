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
    lease_generation: int = 0
    lease_generation_floor: int = 0


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

    def assert_claim(self, *, event_id: str, worker_id: str, lease_generation: int) -> None:
        """Verify a live exact claim at the last safe point before delivery."""
        ...

    def mark_published(self, *, event_id: str, worker_id: str, lease_generation: int | None = None) -> None:
        """Mark a leased event published."""
        ...

    def mark_failed(
        self, *, event_id: str, worker_id: str, error: str, max_attempts: int = 5,
        retry_base_seconds: int = 5, lease_generation: int | None = None
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
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise OutboxError("max_attempts must be between1 and100.")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 86400:
            raise OutboxError("lease_seconds must be between1 and86400.")
        if type(retry_base_seconds) is not int or not 0 <= retry_base_seconds <= 86400:
            raise OutboxError("retry_base_seconds must be between0 and86400.")
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
            self.repository.assert_claim(
                event_id=event.id, worker_id=worker_id, lease_generation=event.lease_generation
            )
            try:
                if callable(publisher):
                    publisher(event)
                else:
                    publisher.publish(event)
            except Exception as exc:  # noqa: BLE001 - publisher failures become retry state.
                failed += 1
                if self.mark_failed(
                    event_id=event.id, worker_id=worker_id, error=str(exc), lease_generation=event.lease_generation
                ):
                    dead_lettered += 1
            else:
                self.mark_published(event_id=event.id, worker_id=worker_id, lease_generation=event.lease_generation)
                published += 1
        return OutboxProcessResult(
            claimed=len(events),
            published=published,
            failed=failed,
            dead_lettered=dead_lettered,
        )

    def mark_published(self, *, event_id: str, worker_id: str, lease_generation: int | None = None) -> None:
        """Mark a leased event published."""
        self.repository.mark_published(event_id=event_id, worker_id=worker_id, lease_generation=lease_generation)

    def mark_failed(
        self, *, event_id: str, worker_id: str, error: str, lease_generation: int | None = None
    ) -> bool:
        """Record a bounded failure and return whether the event entered dead-letter state."""
        return self.repository.mark_failed(
            event_id=event_id,
            worker_id=worker_id,
            error=error,
            max_attempts=self.max_attempts,
            retry_base_seconds=self.retry_base_seconds,
            lease_generation=lease_generation,
        )

    def requeue_dead_letter(self, *, event_id: str) -> None:
        """Reset one dead-lettered event for an explicit operator replay."""
        self.repository.requeue_dead_letter(event_id=event_id)

    def list_events(self, *, status: str = "pending", limit: int = 100) -> list[OutboxEvent]:
        """List events by delivery status in stable order."""
        return self.repository.list_events(status=status, limit=limit)
