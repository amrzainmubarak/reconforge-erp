"""Bounded PostgreSQL transactional-outbox worker runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from threading import Event
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_outbox import PostgresOutboxEvent, PostgresOutboxRepository
from reconforge.platform.outbox import OutboxProcessResult
from reconforge.workers.outbox import OutboxWorkerSettings, WorkerRunSummary
from reconforge.workers.policy import require_service_worker_policy


class PostgresOutboxWorkerError(RuntimeError):
    """Raised when a PostgreSQL outbox worker cycle cannot complete safely."""


class PostgresOutboxWorker:
    """Poll tenant-scoped PostgreSQL outbox rows with explicit publishing."""

    def __init__(
        self,
        connection_factory: Any,
        *,
        tenant_supplier: Callable[[], Iterable[str]],
        publisher: Callable[[PostgresOutboxEvent], None] | Any,
        settings: OutboxWorkerSettings,
    ) -> None:
        self.connection_factory = connection_factory
        self.tenant_supplier = tenant_supplier
        self.publisher = publisher
        self.settings = settings

    def _authorize_tenant(self, tenant_id: str) -> None:
        require_service_worker_policy(
            tenant_id=tenant_id,
            worker_id=self.settings.worker_id,
            actor_id=self.settings.audit_actor_id,
            policy_context_supplier=self.settings.policy_context_supplier,
            policy_permission=self.settings.policy_permission,
            surface="postgres-outbox.worker.claim",
            error_factory=PostgresOutboxWorkerError,
        )

    def _publish(self, event: PostgresOutboxEvent) -> None:
        if callable(self.publisher):
            self.publisher(event)
        else:
            self.publisher.publish(event)

    def _tenant_ids(self) -> list[str]:
        try:
            return sorted(str(tenant_id).strip() for tenant_id in self.tenant_supplier())
        except Exception as exc:
            raise PostgresOutboxWorkerError("Unable to enumerate PostgreSQL outbox tenants.") from exc

    def process_once(self) -> OutboxProcessResult:
        """Claim and deliver one bounded batch per configured tenant."""

        claimed_count = 0
        published_count = 0
        failed_count = 0
        dead_lettered_count = 0
        for tenant_id in self._tenant_ids():
            try:
                self._authorize_tenant(tenant_id)
                with PostgresTenantBoundary(self.connection_factory).transaction(tenant_id) as connection:
                    events = PostgresOutboxRepository(connection).claim_pending(
                        tenant_id=tenant_id,
                        worker_id=self.settings.worker_id,
                        limit=self.settings.batch_size,
                        max_attempts=self.settings.max_attempts,
                        lease_seconds=self.settings.lease_seconds,
                    )
                claimed_count += len(events)
                for event in events:
                    try:
                        self._publish(event)
                    except Exception as exc:  # noqa: BLE001 - publisher failures become retry state.
                        failed_count += 1
                        with PostgresTenantBoundary(self.connection_factory).transaction(tenant_id) as connection:
                            dead_lettered = PostgresOutboxRepository(connection).mark_failed(
                                tenant_id=tenant_id,
                                event_id=event.id,
                                worker_id=self.settings.worker_id,
                                error=str(exc),
                                max_attempts=self.settings.max_attempts,
                                retry_base_seconds=self.settings.retry_base_seconds,
                            )
                        dead_lettered_count += int(dead_lettered)
                    else:
                        with PostgresTenantBoundary(self.connection_factory).transaction(tenant_id) as connection:
                            PostgresOutboxRepository(connection).mark_published(
                                tenant_id=tenant_id,
                                event_id=event.id,
                                worker_id=self.settings.worker_id,
                            )
                        published_count += 1
            except PostgresOutboxWorkerError:
                raise
            except Exception as exc:
                raise PostgresOutboxWorkerError("PostgreSQL outbox worker cycle failed safely.") from exc
        return OutboxProcessResult(
            claimed=claimed_count,
            published=published_count,
            failed=failed_count,
            dead_lettered=dead_lettered_count,
        )

    def run(self, *, stop_event: Event | None = None, max_cycles: int | None = None) -> WorkerRunSummary:
        """Poll until stopped or an optional bounded cycle count is reached."""

        if max_cycles is not None and max_cycles < 1:
            raise PostgresOutboxWorkerError("max_cycles must be positive when supplied.")
        event = stop_event or Event()
        summary = WorkerRunSummary.empty()
        while not event.is_set() and (max_cycles is None or summary.cycles < max_cycles):
            try:
                summary = summary.add(self.process_once())
            except PostgresOutboxWorkerError:
                raise
            if max_cycles is not None and summary.cycles >= max_cycles:
                break
            event.wait(self.settings.poll_interval_seconds)
        return summary
