"""Bounded transactional-outbox worker runtime.

The worker owns one fresh database connection per polling cycle. This avoids
leaking transactions or SQLite connection state across retries and gives a
future PostgreSQL worker the same application-level contract. Delivery remains
explicitly injected; this module does not pretend to be a message broker.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Event

from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.platform.outbox import OutboxEvent, OutboxProcessResult, OutboxPublisher, OutboxService
from reconforge.workers.policy import WorkerPolicyContextSupplier, WorkerPolicyHierarchyContextSupplier


class OutboxWorkerError(RuntimeError):
    """Raised when worker configuration or cycle execution is invalid."""


@dataclass(frozen=True)
class OutboxWorkerSettings:
    """Bounded polling and delivery settings."""

    worker_id: str
    poll_interval_seconds: float = 5.0
    batch_size: int = 50
    max_attempts: int = 5
    lease_seconds: int = 300
    retry_base_seconds: int = 5
    actor_id: str = ""
    policy_context_supplier: Callable[[str], PolicyEvaluationContext] | None = None
    policy_context_scope_supplier: WorkerPolicyContextSupplier | None = None
    policy_context_hierarchy_supplier: WorkerPolicyHierarchyContextSupplier | None = None
    scope_supplier: Callable[[], Iterable[tuple[str, str | None, str | None, str | None]]] | None = None
    max_tenants: int = 10_000
    policy_permission: str = "outbox.publish"

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or len(self.worker_id.strip()) > 160:
            raise OutboxWorkerError("worker_id must be a non-empty value of at most 160 characters.")
        if self.poll_interval_seconds < 0:
            raise OutboxWorkerError("poll_interval_seconds cannot be negative.")
        if not 1 <= self.batch_size <= 1_000:
            raise OutboxWorkerError("batch_size must be between 1 and 1000.")
        if self.max_attempts < 1 or self.lease_seconds < 1 or self.retry_base_seconds < 0:
            raise OutboxWorkerError("Outbox retry and lease settings are invalid.")
        if not 1 <= int(self.max_tenants) <= 100_000:
            raise OutboxWorkerError("max_tenants must be between 1 and 100000.")
        if not self.policy_permission.strip():
            raise OutboxWorkerError("policy_permission must be non-empty when configured.")

    @property
    def audit_actor_id(self) -> str:
        """Return the configured service actor, falling back to worker identity."""

        return self.actor_id.strip() or self.worker_id.strip()


@dataclass(frozen=True)
class WorkerRunSummary:
    """Aggregate delivery counts returned by a bounded worker run."""

    cycles: int
    claimed: int
    published: int
    failed: int
    dead_lettered: int

    @classmethod
    def empty(cls) -> WorkerRunSummary:
        return cls(cycles=0, claimed=0, published=0, failed=0, dead_lettered=0)

    def add(self, result: OutboxProcessResult) -> WorkerRunSummary:
        return WorkerRunSummary(
            cycles=self.cycles + 1,
            claimed=self.claimed + result.claimed,
            published=self.published + result.published,
            failed=self.failed + result.failed,
            dead_lettered=self.dead_lettered + result.dead_lettered,
        )


class OutboxWorker:
    """Run outbox delivery cycles with explicit lifecycle control."""

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection],
        *,
        publisher: OutboxPublisher | Callable[[OutboxEvent], None],
        settings: OutboxWorkerSettings,
    ) -> None:
        self.connection_factory = connection_factory
        self.publisher = publisher
        self.settings = settings

    def process_once(self) -> OutboxProcessResult:
        """Process one bounded batch and close the cycle's connection."""

        connection: sqlite3.Connection | None = None
        try:
            connection = self.connection_factory()
            service = OutboxService(
                connection,
                max_attempts=self.settings.max_attempts,
                lease_seconds=self.settings.lease_seconds,
                retry_base_seconds=self.settings.retry_base_seconds,
            )
            return service.process_once(
                publisher=self.publisher,
                worker_id=self.settings.worker_id,
                limit=self.settings.batch_size,
            )
        except Exception as exc:  # noqa: BLE001 - worker boundary adds safe context and preserves the cause.
            if isinstance(exc, OutboxWorkerError):
                raise
            raise OutboxWorkerError("Outbox worker cycle failed.") from exc
        finally:
            if connection is not None:
                connection.close()

    def run(
        self,
        *,
        stop_event: Event | None = None,
        max_cycles: int | None = None,
    ) -> WorkerRunSummary:
        """Poll until stopped or until an optional bounded cycle count is reached."""

        if max_cycles is not None and max_cycles < 1:
            raise OutboxWorkerError("max_cycles must be positive when supplied.")
        event = stop_event or Event()
        summary = WorkerRunSummary.empty()
        while not event.is_set() and (max_cycles is None or summary.cycles < max_cycles):
            summary = summary.add(self.process_once())
            if max_cycles is not None and summary.cycles >= max_cycles:
                break
            event.wait(self.settings.poll_interval_seconds)
        return summary
