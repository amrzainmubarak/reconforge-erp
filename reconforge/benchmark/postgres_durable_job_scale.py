"""Bounded PostgreSQL multi-worker durable-job scale profile.

This profile is deliberately smaller than the published SQLite 10K/100K
profiles.  It exercises the real PostgreSQL repository, row-lock claiming,
tenant RLS, lease fencing, and partition-effect uniqueness with several
independent connections.  Runtime and throughput are recorded as observations
only; the structural result is the evidence-bearing part of the manifest.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    JobSubmission,
    LeasedJob,
)
from reconforge.domain.jobs import JobOutputManifest, JobStatus
from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository

POSTGRES_SCALE_SCHEMA_VERSION = 1
POSTGRES_SCALE_WORKER_VERSION = "postgres-durable-job-scale/1.0.0"


@dataclass(frozen=True)
class PostgresDurableJobScaleProfile:
    """Declared shape for one bounded PostgreSQL concurrency run."""

    profile_id: str
    workers: int
    jobs_per_tenant: int
    partitions_per_job: int
    tenants: int
    lease_seconds: int = 600

    def __post_init__(self) -> None:
        if self.workers < 1 or self.jobs_per_tenant < 1 or self.partitions_per_job < 1:
            raise ValueError("workers, jobs_per_tenant, and partitions_per_job must be positive")
        if self.tenants < 1 or self.workers % self.tenants != 0:
            raise ValueError("workers must be an exact multiple of a positive tenant count")
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")

    @property
    def jobs(self) -> int:
        return self.jobs_per_tenant * self.tenants

    @property
    def declared_partition_effects(self) -> int:
        return self.jobs * self.partitions_per_job


@dataclass(frozen=True)
class PostgresDurableJobScaleResult:
    """Structural result plus explicitly non-claim timing observations."""

    schema_version: int
    profile_id: str
    workers: int
    jobs: int
    jobs_per_tenant: int
    partitions_per_job: int
    tenants: int
    declared_partition_effects: int
    completed_jobs: int
    committed_partition_effects: int
    duplicate_partition_effects: int
    final_queue_depth: int
    final_running_depth: int
    per_tenant_completions: dict[str, int]
    effect_set_digest: str
    observed_runtime_seconds: float
    observed_throughput_jobs_per_second: float
    environment: dict[str, object]
    manifest_digest: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def default_profile() -> PostgresDurableJobScaleProfile:
    """Return the hosted server-boundary profile (256 committed effects)."""

    return PostgresDurableJobScaleProfile(
        profile_id="postgres-durable-job-load/256-effects-v1",
        workers=8,
        jobs_per_tenant=16,
        partitions_per_job=4,
        tenants=4,
    )


def ten_k_profile() -> PostgresDurableJobScaleProfile:
    """Return the larger hosted PostgreSQL correctness tier (10K effects)."""

    return PostgresDurableJobScaleProfile(
        profile_id="postgres-durable-job-load/10k-effects-v1",
        workers=16,
        jobs_per_tenant=625,
        partitions_per_job=4,
        tenants=4,
    )


def _utc_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _submission(*, job_id: str, tenant_id: str, index: int, profile: PostgresDurableJobScaleProfile) -> JobSubmission:
    return JobSubmission(
        job_id=job_id,
        idempotency_scope=f"{profile.profile_id}/{tenant_id}",
        idempotency_key=f"scale-key-{index:05d}",
        tenant_id=tenant_id,
        workspace_id="scale-workspace",
        entity_id="scale-entity",
        input_digest=_digest(f"input:{index}"),
        config_digest=_digest(f"config:{profile.profile_id}"),
        worker_version=POSTGRES_SCALE_WORKER_VERSION,
        total_units=profile.partitions_per_job,
        retry_ceiling=2,
        created_at="2026-08-03T00:00:00Z",
    )


def _drain(worker: DurableJobWorkerService, leased: LeasedJob, profile: PostgresDurableJobScaleProfile) -> None:
    completed = len(worker.completed_effects(leased))
    while completed < profile.partitions_per_job:
        ordinal = completed + 1
        job_id = leased.job.id
        output_digest = _digest(f"{job_id}:output:{ordinal}")
        input_digest = _digest(f"{job_id}:input:{ordinal}")
        occurred_at = f"2026-08-03T00:01:{ordinal:02d}Z"
        if ordinal < profile.partitions_per_job:
            leased = worker.commit_partition(
                leased,
                partition_key=f"partition/{ordinal:04d}",
                ordinal=ordinal,
                completed_units=ordinal,
                input_digest=input_digest,
                output_digest=output_digest,
                effect_reference=f"effect/{job_id}/{ordinal:04d}",
                occurred_at=occurred_at,
            )
        else:
            worker.complete_partition(
                leased,
                partition_key=f"partition/{ordinal:04d}",
                ordinal=ordinal,
                input_digest=input_digest,
                output_digest=output_digest,
                effect_reference=f"effect/{job_id}/{ordinal:04d}",
                occurred_at=occurred_at,
                output_manifest=JobOutputManifest(
                    schema_version=1,
                    digest=_digest(f"{job_id}:manifest"),
                    reference=f"manifest/{job_id}/v1",
                ),
            )
        completed = ordinal


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": int(os.cpu_count() or 1),
        "database": "PostgreSQL",
    }


def _manifest_digest(document: dict[str, object]) -> str:
    stable = {
        key: value
        for key, value in document.items()
        if key not in {"observed_runtime_seconds", "observed_throughput_jobs_per_second", "manifest_digest", "environment"}
    }
    return _digest(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


LIMITATIONS = (
    "This is a bounded synthetic PostgreSQL 16 CI service run with one database host and independent worker connections.",
    "Observed runtime and throughput are hardware/load observations, not an SLO, capacity, or sizing claim.",
    "The declared profile shape is recorded in the result; larger tiers, soak, and backpressure coupling remain unverified here.",
    "Queue HA, automatic failover, host loss, cross-host fairness, RPO/RTO, and production deployment remain unverified.",
)


def _limitations(profile: PostgresDurableJobScaleProfile) -> tuple[str, ...]:
    return (
        LIMITATIONS[0],
        LIMITATIONS[1],
        (
            "The declared profile is "
            f"{profile.workers} workers, {profile.jobs} jobs, "
            f"{profile.partitions_per_job} partitions per job, {profile.tenants} tenant lanes, "
            f"and {profile.declared_partition_effects} committed effects; larger tiers, soak, "
            "and backpressure coupling remain unverified here."
        ),
        LIMITATIONS[3],
    )


def run_postgres_durable_job_scale_profile(
    connection_factory: Callable[[], Any],
    application: DurableJobApplicationService,
    tenant_ids: Sequence[str],
    *,
    profile: PostgresDurableJobScaleProfile | None = None,
    id_prefix: str = "PGSCALE",
) -> PostgresDurableJobScaleResult:
    """Submit and concurrently drain one bounded PostgreSQL profile.

    The caller owns schema setup and tenant creation.  Each worker obtains a
    fresh connection from ``connection_factory``; no shared connection is used
    across threads.
    """

    declared = profile or default_profile()
    limitations = _limitations(declared)
    tenants = tuple(str(value) for value in tenant_ids)
    if len(tenants) != declared.tenants or len(set(tenants)) != len(tenants):
        raise ValueError("tenant_ids must contain exactly the unique declared tenant lanes")
    jobs_by_tenant: dict[str, list[str]] = {tenant: [] for tenant in tenants}
    for index in range(declared.jobs):
        tenant = tenants[index % declared.tenants]
        job_id = f"{id_prefix}-JOB-{index:05d}"
        application.submit(_submission(job_id=job_id, tenant_id=tenant, index=index, profile=declared), actor_id="scale-submitter")
        jobs_by_tenant[tenant].append(job_id)

    counts = {f"lane-{index:02d}": 0 for index in range(declared.tenants)}
    lock = threading.Lock()
    started = time.perf_counter()

    def worker_loop(worker_index: int, tenant_index: int) -> None:
        tenant = tenants[tenant_index]
        lane_key = f"lane-{tenant_index:02d}"
        connection = connection_factory()
        try:
            worker = DurableJobWorkerService(PostgresDurableJobRepository(connection))
            while True:
                with lock:
                    if counts[lane_key] >= declared.jobs_per_tenant:
                        return
                leased = worker.claim(
                    tenant_id=tenant,
                    workspace_id="scale-workspace",
                    entity_id="scale-entity",
                    worker_id=f"pg-scale-worker-{worker_index:02d}",
                    occurred_at="2026-08-03T00:00:10Z",
                    lease_expires_at="2026-08-03T10:00:00Z",
                )
                if leased is None:
                    time.sleep(0.002)
                    continue
                _drain(worker, leased, declared)
                with lock:
                    counts[lane_key] += 1
        finally:
            connection.close()

    workers_per_tenant = declared.workers // declared.tenants
    with ThreadPoolExecutor(max_workers=declared.workers, thread_name_prefix="reconforge-pg-scale") as pool:
        futures = [
            pool.submit(worker_loop, worker_index, tenant_index)
            for tenant_index in range(declared.tenants)
            for worker_index in range(tenant_index * workers_per_tenant, (tenant_index + 1) * workers_per_tenant)
        ]
        for future in futures:
            future.result()
    runtime = max(time.perf_counter() - started, 0.0)

    effect_rows: list[tuple[str, int, str, str, str]] = []
    completed_jobs = 0
    duplicate_partition_effects = 0
    final_queue_depth = 0
    final_running_depth = 0
    audit_connection = connection_factory()
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
                    effect_rows.append((job_id, effect.ordinal, effect.input_digest, effect.output_digest, effect.effect_reference))
            with audit_connection.transaction():
                set_local_tenant_scope(audit_connection, tenant, workspace_id="scale-workspace")
                row = audit_connection.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status IN ('queued','retrying')),
                           COUNT(*) FILTER (WHERE status = 'running')
                    FROM reconforge.durable_jobs
                    WHERE tenant_id = %s
                    """,
                    (tenant,),
                ).fetchone()
                final_queue_depth += int(row[0])
                final_running_depth += int(row[1])
    finally:
        audit_connection.close()

    serialized = json.dumps(
        {"schema_version": POSTGRES_SCALE_SCHEMA_VERSION, "profile_id": declared.profile_id, "rows": sorted(effect_rows)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    effect_digest = _digest(serialized)
    document: dict[str, object] = {
        "schema_version": POSTGRES_SCALE_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "jobs": declared.jobs,
        "jobs_per_tenant": declared.jobs_per_tenant,
        "partitions_per_job": declared.partitions_per_job,
        "tenants": declared.tenants,
        "declared_partition_effects": declared.declared_partition_effects,
        "completed_jobs": completed_jobs,
        "committed_partition_effects": len(effect_rows),
        "duplicate_partition_effects": duplicate_partition_effects,
        "final_queue_depth": final_queue_depth,
        "final_running_depth": final_running_depth,
        "per_tenant_completions": dict(sorted(counts.items())),
        "effect_set_digest": effect_digest,
        "limitations": list(limitations),
    }
    manifest_digest = _manifest_digest(document)
    return PostgresDurableJobScaleResult(
        schema_version=POSTGRES_SCALE_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        jobs=declared.jobs,
        jobs_per_tenant=declared.jobs_per_tenant,
        partitions_per_job=declared.partitions_per_job,
        tenants=declared.tenants,
        declared_partition_effects=declared.declared_partition_effects,
        completed_jobs=completed_jobs,
        committed_partition_effects=len(effect_rows),
        duplicate_partition_effects=duplicate_partition_effects,
        final_queue_depth=final_queue_depth,
        final_running_depth=final_running_depth,
        per_tenant_completions=dict(sorted(counts.items())),
        effect_set_digest=effect_digest,
        observed_runtime_seconds=round(runtime, 4),
        observed_throughput_jobs_per_second=round(completed_jobs / runtime, 4) if runtime else 0.0,
        environment=_environment(),
        manifest_digest=manifest_digest,
        limitations=limitations,
    )


def verify_postgres_durable_job_scale_result(
    result: PostgresDurableJobScaleResult,
    *,
    profile: PostgresDurableJobScaleProfile | None = None,
) -> None:
    """Assert the structural invariants of the bounded PostgreSQL profile."""

    declared = profile or default_profile()
    if result.schema_version != POSTGRES_SCALE_SCHEMA_VERSION or result.profile_id != declared.profile_id:
        raise AssertionError("PostgreSQL scale result schema/profile mismatch")
    if result.workers != declared.workers or result.jobs != declared.jobs or result.tenants != declared.tenants:
        raise AssertionError("PostgreSQL scale result declared shape mismatch")
    if result.completed_jobs != declared.jobs or result.committed_partition_effects != declared.declared_partition_effects:
        raise AssertionError("PostgreSQL scale profile did not complete its declared workload")
    if result.duplicate_partition_effects != 0 or result.final_queue_depth != 0 or result.final_running_depth != 0:
        raise AssertionError("PostgreSQL scale profile left duplicate effects or unfinished work")
    if result.per_tenant_completions != {f"lane-{index:02d}": declared.jobs_per_tenant for index in range(declared.tenants)}:
        raise AssertionError("PostgreSQL scale profile did not complete each tenant lane")
    if not result.effect_set_digest or not result.manifest_digest:
        raise AssertionError("PostgreSQL scale result is missing integrity digests")


__all__ = [
    "LIMITATIONS",
    "POSTGRES_SCALE_SCHEMA_VERSION",
    "PostgresDurableJobScaleProfile",
    "PostgresDurableJobScaleResult",
    "default_profile",
    "ten_k_profile",
    "run_postgres_durable_job_scale_profile",
    "verify_postgres_durable_job_scale_result",
]
