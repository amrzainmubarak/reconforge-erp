"""Hosted single-node PostgreSQL scheduler polling runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Any

from reconforge.application.scheduler import ScheduleProcessResult, SchedulerApplicationService
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_scheduler import PostgresScheduleRepository
from reconforge.workers.policy import WorkerPolicyContextSupplier, require_service_worker_policy


class PostgresSchedulerWorkerError(RuntimeError):
    """Raised when a scheduler polling cycle cannot complete safely."""


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@dataclass(frozen=True)
class PostgresSchedulerWorkerSettings:
    worker_id: str
    poll_interval_seconds: float = 5.0
    batch_size: int = 50
    max_tenants: int = 10_000
    actor_id: str = ""
    policy_context_supplier: Callable[[str], PolicyEvaluationContext] | None = None
    policy_context_scope_supplier: WorkerPolicyContextSupplier | None = None
    scope_supplier: Callable[[], Iterable[tuple[str, str | None, str | None]]] | None = None
    policy_permission: str = "schedule.run"

    def __post_init__(self) -> None:
        normalized = str(self.worker_id or "").strip()
        if not normalized or len(normalized) > 160:
            raise PostgresSchedulerWorkerError("worker_id must be a non-empty value of at most 160 characters.")
        object.__setattr__(self, "worker_id", normalized)
        if not 0 <= float(self.poll_interval_seconds) <= 3_600:
            raise PostgresSchedulerWorkerError("poll_interval_seconds must be between 0 and 3600.")
        if not 1 <= int(self.batch_size) <= 1_000:
            raise PostgresSchedulerWorkerError("batch_size must be between 1 and 1000.")
        if not 1 <= int(self.max_tenants) <= 100_000:
            raise PostgresSchedulerWorkerError("max_tenants must be between 1 and 100000.")
        if not self.policy_permission.strip():
            raise PostgresSchedulerWorkerError("policy_permission must be non-empty when configured.")

    @property
    def audit_actor_id(self) -> str:
        """Return the configured service actor, falling back to worker identity."""

        return self.actor_id.strip() or self.worker_id.strip()


@dataclass(frozen=True)
class SchedulerWorkerRunSummary:
    cycles: int = 0
    tenants_processed: int = 0
    schedules_claimed: int = 0
    schedules_evaluated: int = 0
    occurrences_due: int = 0
    dispatched: int = 0
    replayed: int = 0
    skipped: int = 0
    deferred: int = 0
    nonexistent_local_times: int = 0

    def add_cycle(self, results: Iterable[ScheduleProcessResult]) -> SchedulerWorkerRunSummary:
        items = tuple(results)
        return SchedulerWorkerRunSummary(
            cycles=self.cycles + 1,
            tenants_processed=self.tenants_processed + len(items),
            schedules_claimed=self.schedules_claimed + sum(item.schedules_claimed for item in items),
            schedules_evaluated=self.schedules_evaluated + sum(item.schedules_evaluated for item in items),
            occurrences_due=self.occurrences_due + sum(item.occurrences_due for item in items),
            dispatched=self.dispatched + sum(item.dispatched for item in items),
            replayed=self.replayed + sum(item.replayed for item in items),
            skipped=self.skipped + sum(item.skipped for item in items),
            deferred=self.deferred + sum(item.deferred for item in items),
            nonexistent_local_times=self.nonexistent_local_times
            + sum(item.nonexistent_local_times for item in items),
        )


class PostgresSchedulerWorker:
    """Poll configured tenants with one fresh connection per tenant and cycle."""

    def __init__(
        self,
        connection_factory: Any,
        *,
        tenant_supplier: Callable[[], Iterable[str]],
        settings: PostgresSchedulerWorkerSettings,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.connection_factory = connection_factory
        self.tenant_supplier = tenant_supplier
        self.settings = settings
        self.clock = clock

    def _tenant_ids(self) -> tuple[str, ...]:
        try:
            tenant_ids = tuple(sorted({validate_tenant_id(value) for value in self.tenant_supplier()}))
        except Exception as exc:
            raise PostgresSchedulerWorkerError("Unable to enumerate scheduler tenants.") from exc
        if len(tenant_ids) > self.settings.max_tenants:
            raise PostgresSchedulerWorkerError("Scheduler tenant enumeration exceeds its configured bound.")
        return tenant_ids

    def _lanes(self) -> tuple[tuple[str, str | None, str | None], ...]:
        """Return deterministic tenant/workspace/entity lanes for one cycle."""

        if self.settings.scope_supplier is None:
            return tuple((tenant_id, None, None) for tenant_id in self._tenant_ids())
        try:
            lanes: set[tuple[str, str | None, str | None]] = set()
            for raw_lane in self.settings.scope_supplier():
                if not isinstance(raw_lane, tuple) or len(raw_lane) != 3:
                    raise PostgresSchedulerWorkerError(
                        "Scheduler scope supplier must return (tenant, workspace, entity) tuples."
                    )
                tenant_id = validate_tenant_id(raw_lane[0])
                workspace_id = str(raw_lane[1] or "").strip() or None
                entity_id = str(raw_lane[2] or "").strip() or None
                if entity_id is not None and workspace_id is None:
                    raise PostgresSchedulerWorkerError("Scheduler entity scope requires workspace scope.")
                lanes.add((tenant_id, workspace_id, entity_id))
            if len({tenant for tenant, _, _ in lanes}) > self.settings.max_tenants:
                raise PostgresSchedulerWorkerError("Scheduler tenant enumeration exceeds its configured bound.")
            return tuple(sorted(lanes, key=lambda lane: (lane[0], lane[1] or "", lane[2] or "")))
        except PostgresSchedulerWorkerError:
            raise
        except Exception as exc:
            raise PostgresSchedulerWorkerError("Unable to enumerate scheduler scope lanes.") from exc

    def process_once(self) -> tuple[ScheduleProcessResult, ...]:
        try:
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise PostgresSchedulerWorkerError("Scheduler clock must return a timezone-aware timestamp.")
            current = now.astimezone(UTC).replace(microsecond=0)
            results: list[ScheduleProcessResult] = []
            for tenant_id, workspace_id, entity_id in self._lanes():
                require_service_worker_policy(
                    tenant_id=tenant_id,
                    worker_id=self.settings.worker_id,
                    actor_id=self.settings.audit_actor_id,
                    policy_context_supplier=self.settings.policy_context_supplier,
                    policy_context_scope_supplier=self.settings.policy_context_scope_supplier,
                    workspace_id=workspace_id,
                    entity_id=entity_id,
                    policy_permission=self.settings.policy_permission,
                    surface="postgres-scheduler.worker.claim",
                    error_factory=PostgresSchedulerWorkerError,
                )
                connection = self.connection_factory.connect()
                try:
                    # Re-evaluate immediately before dispatching due work. A
                    # lane can be revoked after the pre-connection check while
                    # the scheduler is waiting to enter its repository
                    # transaction; no schedule mutation is allowed after that
                    # revocation point.
                    require_service_worker_policy(
                        tenant_id=tenant_id,
                        worker_id=self.settings.worker_id,
                        actor_id=self.settings.audit_actor_id,
                        policy_context_supplier=self.settings.policy_context_supplier,
                        policy_context_scope_supplier=self.settings.policy_context_scope_supplier,
                        workspace_id=workspace_id,
                        entity_id=entity_id,
                        policy_permission=self.settings.policy_permission,
                        surface="postgres-scheduler.worker.dispatch",
                        error_factory=PostgresSchedulerWorkerError,
                    )
                    result = SchedulerApplicationService(PostgresScheduleRepository(connection)).process_due(
                        tenant_id=tenant_id,
                        worker_id=self.settings.worker_id,
                        now=current,
                        limit=self.settings.batch_size,
                        **(
                            {"workspace_id": workspace_id, "entity_id": entity_id}
                            if workspace_id is not None or entity_id is not None
                            else {}
                        ),
                    )
                    results.append(result)
                finally:
                    connection.close()
            return tuple(results)
        except PostgresSchedulerWorkerError:
            raise
        except Exception as exc:
            raise PostgresSchedulerWorkerError("PostgreSQL scheduler worker cycle failed safely.") from exc

    def run(
        self,
        *,
        stop_event: Event | None = None,
        max_cycles: int | None = None,
    ) -> SchedulerWorkerRunSummary:
        if max_cycles is not None and max_cycles < 1:
            raise PostgresSchedulerWorkerError("max_cycles must be positive when supplied.")
        event = stop_event or Event()
        summary = SchedulerWorkerRunSummary()
        while not event.is_set() and (max_cycles is None or summary.cycles < max_cycles):
            summary = summary.add_cycle(self.process_once())
            if max_cycles is not None and summary.cycles >= max_cycles:
                break
            event.wait(self.settings.poll_interval_seconds)
        return summary


__all__ = [
    "PostgresSchedulerWorker",
    "PostgresSchedulerWorkerError",
    "PostgresSchedulerWorkerSettings",
    "SchedulerWorkerRunSummary",
]
