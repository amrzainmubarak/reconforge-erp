"""Bounded PostgreSQL durable-job producer/backpressure profile.

This profile exercises the atomic execution-lane queue cap together with real
PostgreSQL claim/lease workers. It proves only bounded correctness and queue
drain for the declared synthetic shape; it is not a capacity, soak, HA, or
production-sizing benchmark.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService
from reconforge.benchmark.postgres_durable_job_scale import (
    PostgresDurableJobScaleProfile,
    _digest,
    _drain,
    _environment,
    _submission,
)
from reconforge.domain.jobs import DurableJobBackpressureError, JobStatus
from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository

POSTGRES_BACKPRESSURE_SCHEMA_VERSION = 1
POSTGRES_BACKPRESSURE_PROFILE_ID = "postgres-durable-job-load/backpressure-tier-v1"


@dataclass(frozen=True)
class PostgresDurableJobBackpressureProfile:
    """Declared shape for one bounded PostgreSQL producer/worker run."""

    profile_id: str = POSTGRES_BACKPRESSURE_PROFILE_ID
    workers: int = 8
    jobs_per_tenant: int = 16
    partitions_per_job: int = 4
    tenants: int = 4
    max_queued_jobs: int = 4

    def __post_init__(self) -> None:
        if self.workers < 1 or self.jobs_per_tenant < 1 or self.partitions_per_job < 1:
            raise ValueError("workers, jobs_per_tenant, and partitions_per_job must be positive")
        if self.tenants < 1 or self.workers % self.tenants != 0:
            raise ValueError("workers must be an exact multiple of a positive tenant count")
        if self.max_queued_jobs < 1 or self.max_queued_jobs > self.jobs_per_tenant:
            raise ValueError("max_queued_jobs must be positive and fit the declared tenant workload")

    @property
    def jobs(self) -> int:
        return self.jobs_per_tenant * self.tenants

    @property
    def declared_partition_effects(self) -> int:
        return self.jobs * self.partitions_per_job

    def scale_profile(self) -> PostgresDurableJobScaleProfile:
        return PostgresDurableJobScaleProfile(
            profile_id=self.profile_id,
            workers=self.workers,
            jobs_per_tenant=self.jobs_per_tenant,
            partitions_per_job=self.partitions_per_job,
            tenants=self.tenants,
        )


@dataclass(frozen=True)
class PostgresDurableJobBackpressureResult:
    """Structural result plus explicitly non-claim timing observations."""

    schema_version: int
    profile_id: str
    workers: int
    jobs: int
    jobs_per_tenant: int
    partitions_per_job: int
    tenants: int
    max_queued_jobs: int
    submitted_jobs: int
    rejected_attempts: int
    completed_jobs: int
    committed_partition_effects: int
    duplicate_partition_effects: int
    observed_max_queue_depth: int
    final_queue_depth: int
    final_running_depth: int
    per_tenant_completions: dict[str, int]
    effect_set_digest: str
    observed_runtime_seconds: float
    environment: dict[str, object]
    manifest_digest: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


LIMITATIONS = (
    "This is a bounded synthetic PostgreSQL queue-cap run with one database host and independent producer/worker connections.",
    "The observed queue depth and retry attempts are workload observations, not a capacity, throughput, or SLO claim.",
    "Queue HA, automatic failover, host loss, cross-host fairness, soak, RPO/RTO, and production deployment remain unverified.",
)


def default_profile() -> PostgresDurableJobBackpressureProfile:
    """Return the small hosted queue-cap profile (256 partition effects)."""

    return PostgresDurableJobBackpressureProfile()


def _queue_depth(connection_factory: Callable[[], Any], tenant_id: str) -> int:
    connection = connection_factory()
    try:
        with connection.transaction():
            set_local_tenant_scope(connection, tenant_id, workspace_id="backpressure-workspace")
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM reconforge.durable_jobs
                WHERE tenant_id = %s AND workspace_id = %s AND entity_id = %s
                  AND status IN ('queued', 'retrying')
                """,
                (tenant_id, "backpressure-workspace", "backpressure-entity"),
            ).fetchone()
            return int(row[0])
    finally:
        connection.close()


def _manifest_digest(document: dict[str, object]) -> str:
    stable = {
        key: value
        for key, value in document.items()
        if key not in {"observed_runtime_seconds", "manifest_digest", "environment"}
    }
    return _digest(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def run_postgres_durable_job_backpressure_profile(
    connection_factory: Callable[[], Any],
    application: DurableJobApplicationService,
    tenant_ids: Sequence[str],
    *,
    profile: PostgresDurableJobBackpressureProfile | None = None,
    id_prefix: str = "PGBACKPRESSURE",
) -> PostgresDurableJobBackpressureResult:
    """Run bounded producers and workers against one PostgreSQL queue profile."""

    declared = profile or default_profile()
    tenants = tuple(str(value) for value in tenant_ids)
    if len(tenants) != declared.tenants or len(set(tenants)) != len(tenants):
        raise ValueError("tenant_ids must contain exactly the unique declared tenant lanes")
    scale = declared.scale_profile()
    jobs_by_tenant: dict[str, list[str]] = {tenant: [] for tenant in tenants}
    counts = {f"lane-{index:02d}": 0 for index in range(declared.tenants)}
    lock = threading.Lock()
    observed_max = [0]
    rejected_attempts = [0]
    submitted_jobs = [0]
    started = time.perf_counter()

    def producer(tenant_index: int) -> None:
        tenant = tenants[tenant_index]
        producer_connection = connection_factory()
        try:
            producer_service = DurableJobApplicationService(PostgresDurableJobRepository(producer_connection))
            for local_index in range(declared.jobs_per_tenant):
                index = tenant_index * declared.jobs_per_tenant + local_index
                job_id = f"{id_prefix}-JOB-{index:05d}"
                submission = replace(
                    _submission(job_id=job_id, tenant_id=tenant, index=index, profile=scale),
                    workspace_id="backpressure-workspace",
                    entity_id="backpressure-entity",
                )
                while True:
                    try:
                        producer_service.submit_bounded(
                            submission,
                            actor_id="postgres-backpressure-producer",
                            max_queued_jobs=declared.max_queued_jobs,
                        )
                        break
                    except DurableJobBackpressureError:
                        with lock:
                            rejected_attempts[0] += 1
                        time.sleep(0.002)
                with lock:
                    jobs_by_tenant[tenant].append(job_id)
                    submitted_jobs[0] += 1
                depth = _queue_depth(connection_factory, tenant)
                with lock:
                    observed_max[0] = max(observed_max[0], depth)
        finally:
            producer_connection.close()

    def worker(worker_index: int, tenant_index: int) -> None:
        tenant = tenants[tenant_index]
        lane_key = f"lane-{tenant_index:02d}"
        worker_connection = connection_factory()
        try:
            durable_worker = DurableJobWorkerService(PostgresDurableJobRepository(worker_connection))
            while True:
                with lock:
                    if counts[lane_key] >= declared.jobs_per_tenant:
                        return
                leased = durable_worker.claim(
                    tenant_id=tenant,
                    workspace_id="backpressure-workspace",
                    entity_id="backpressure-entity",
                    worker_id=f"pg-backpressure-worker-{worker_index:02d}",
                    # Keep claim/lease timestamps aligned with the bounded
                    # synthetic partition timestamps emitted by ``_drain``.
                    occurred_at="2026-08-03T00:00:10Z",
                    lease_expires_at="2026-08-03T10:00:00Z",
                )
                if leased is None:
                    time.sleep(0.002)
                    continue
                _drain(durable_worker, leased, scale)
                with lock:
                    counts[lane_key] += 1
        finally:
            worker_connection.close()

    workers_per_tenant = declared.workers // declared.tenants
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(
        max_workers=declared.workers + declared.tenants, thread_name_prefix="reconforge-pg-backpressure"
    ) as pool:
        # Submit every lane before awaiting results so producers can block on
        # the bounded queue while workers drain it. Await workers first so a
        # worker failure cannot be hidden behind a producer retry loop.
        worker_futures = [
            pool.submit(worker, worker_index, tenant_index)
            for tenant_index in range(declared.tenants)
            for worker_index in range(
                tenant_index * workers_per_tenant, (tenant_index + 1) * workers_per_tenant
            )
        ]
        producer_futures = [pool.submit(producer, tenant_index) for tenant_index in range(declared.tenants)]
        for future in [*worker_futures, *producer_futures]:
            future.result()
    runtime = max(time.perf_counter() - started, 0.0)

    audit_connection = connection_factory()
    effect_rows: list[tuple[str, int, str, str, str]] = []
    completed_jobs = 0
    duplicate_partition_effects = 0
    final_queue_depth = 0
    final_running_depth = 0
    try:
        audit_repository = PostgresDurableJobRepository(audit_connection)
        for tenant in tenants:
            for job_id in jobs_by_tenant[tenant]:
                job = audit_repository.get(tenant_id=tenant, job_id=job_id)
                if job is None or job.status is not JobStatus.COMPLETED:
                    continue
                completed_jobs += 1
                effects = audit_repository.list_partition_effects(tenant_id=tenant, job_id=job_id)
                seen: set[tuple[str, int]] = set()
                for effect in effects:
                    key = (effect.partition_key, effect.ordinal)
                    if key in seen:
                        duplicate_partition_effects += 1
                    seen.add(key)
                    effect_rows.append(
                        (job_id, effect.ordinal, effect.input_digest, effect.output_digest, effect.effect_reference)
                    )
            with audit_connection.transaction():
                set_local_tenant_scope(audit_connection, tenant, workspace_id="backpressure-workspace")
                row = audit_connection.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status IN ('queued','retrying')),
                           COUNT(*) FILTER (WHERE status = 'running')
                    FROM reconforge.durable_jobs
                    WHERE tenant_id = %s AND workspace_id = %s AND entity_id = %s
                    """,
                    (tenant, "backpressure-workspace", "backpressure-entity"),
                ).fetchone()
                final_queue_depth += int(row[0])
                final_running_depth += int(row[1])
    finally:
        audit_connection.close()

    serialized = json.dumps(
        {"schema_version": POSTGRES_BACKPRESSURE_SCHEMA_VERSION, "profile_id": declared.profile_id, "rows": sorted(effect_rows)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    effect_digest = _digest(serialized)
    limitations = (
        LIMITATIONS[0],
        LIMITATIONS[1],
        (
            f"The declared profile is {declared.workers} workers, {declared.jobs} jobs, "
            f"{declared.partitions_per_job} partitions per job, {declared.tenants} tenant lanes, "
            f"and a {declared.max_queued_jobs}-job queued/retrying cap per lane."
        ),
        LIMITATIONS[2],
    )
    document: dict[str, object] = {
        "schema_version": POSTGRES_BACKPRESSURE_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "jobs": declared.jobs,
        "jobs_per_tenant": declared.jobs_per_tenant,
        "partitions_per_job": declared.partitions_per_job,
        "tenants": declared.tenants,
        "max_queued_jobs": declared.max_queued_jobs,
        "submitted_jobs": submitted_jobs[0],
        "rejected_attempts": rejected_attempts[0],
        "completed_jobs": completed_jobs,
        "committed_partition_effects": len(effect_rows),
        "duplicate_partition_effects": duplicate_partition_effects,
        "observed_max_queue_depth": observed_max[0],
        "final_queue_depth": final_queue_depth,
        "final_running_depth": final_running_depth,
        "per_tenant_completions": dict(sorted(counts.items())),
        "effect_set_digest": effect_digest,
        "limitations": list(limitations),
    }
    return PostgresDurableJobBackpressureResult(
        schema_version=POSTGRES_BACKPRESSURE_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        jobs=declared.jobs,
        jobs_per_tenant=declared.jobs_per_tenant,
        partitions_per_job=declared.partitions_per_job,
        tenants=declared.tenants,
        max_queued_jobs=declared.max_queued_jobs,
        submitted_jobs=submitted_jobs[0],
        rejected_attempts=rejected_attempts[0],
        completed_jobs=completed_jobs,
        committed_partition_effects=len(effect_rows),
        duplicate_partition_effects=duplicate_partition_effects,
        observed_max_queue_depth=observed_max[0],
        final_queue_depth=final_queue_depth,
        final_running_depth=final_running_depth,
        per_tenant_completions=dict(sorted(counts.items())),
        effect_set_digest=effect_digest,
        observed_runtime_seconds=round(runtime, 4),
        environment=_environment(),
        manifest_digest=_manifest_digest(document),
        limitations=limitations,
    )


def verify_postgres_durable_job_backpressure_result(
    result: PostgresDurableJobBackpressureResult,
    *,
    profile: PostgresDurableJobBackpressureProfile | None = None,
) -> None:
    """Assert structural queue-cap, completion, drain, and effect invariants."""

    declared = profile or default_profile()
    if result.schema_version != POSTGRES_BACKPRESSURE_SCHEMA_VERSION or result.profile_id != declared.profile_id:
        raise AssertionError("PostgreSQL backpressure result schema/profile mismatch")
    if result.submitted_jobs != declared.jobs or result.completed_jobs != declared.jobs:
        raise AssertionError("PostgreSQL backpressure profile did not submit and complete its workload")
    if result.committed_partition_effects != declared.declared_partition_effects:
        raise AssertionError("PostgreSQL backpressure profile committed the wrong effect cardinality")
    if result.observed_max_queue_depth > declared.max_queued_jobs:
        raise AssertionError("PostgreSQL producer exceeded its queue cap")
    if result.duplicate_partition_effects != 0 or result.final_queue_depth != 0 or result.final_running_depth != 0:
        raise AssertionError("PostgreSQL backpressure profile left duplicate effects or unfinished work")
    expected = {f"lane-{index:02d}": declared.jobs_per_tenant for index in range(declared.tenants)}
    if result.per_tenant_completions != expected:
        raise AssertionError("PostgreSQL backpressure profile did not complete each tenant lane")
    if not result.effect_set_digest or not result.manifest_digest:
        raise AssertionError("PostgreSQL backpressure result is missing integrity digests")


__all__ = [
    "POSTGRES_BACKPRESSURE_PROFILE_ID",
    "POSTGRES_BACKPRESSURE_SCHEMA_VERSION",
    "PostgresDurableJobBackpressureProfile",
    "PostgresDurableJobBackpressureResult",
    "default_profile",
    "run_postgres_durable_job_backpressure_profile",
    "verify_postgres_durable_job_backpressure_result",
]
