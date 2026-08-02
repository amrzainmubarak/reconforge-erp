"""Reproducible multi-worker durable-job load profile (P4-SCL-001 first slice).

This harness drives the existing durable-job worker loop (claim, commit
partition, complete partition) under real concurrent contention and proves:

* every declared job completes exactly once,
* partition effects are never duplicated under contention,
* the queue drains to zero with no orphaned running jobs,
* a closed schema-v1 manifest records the structural outcome with a
  deterministic digest that is reproducible across runs and environments,
  plus observed timing/memory counters that are explicitly non-claims.

This is the smallest reversible vertical slice for P4-SCL-001. It reuses the
already-proved generation-fenced lease and checkpoint/resume contract. It
does not introduce a new persistence primitive, change the durable-job
domain, or claim a published scale tier. Cancellation-under-load,
backpressure, soak, retry coupling, and 10K/100K/1M tier publication remain
later P4-SCL-001 slices.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sqlite3
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    JobSubmission,
    LeasedJob,
)
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobOutputManifest
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository

LOAD_PROFILE_SCHEMA_VERSION = 1
DEFAULT_PROFILE_ID = "durable-job-load/small-tier-v1"
DEFAULT_WORKERS = 8
DEFAULT_JOBS = 64
DEFAULT_PARTITIONS_PER_JOB = 4
DEFAULT_TENANTS = 4
DEFAULT_LEASE_SECONDS = 30
WORKER_VERSION = "durable-job-load-harness/1.0.0"


@dataclass(frozen=True)
class DurableJobLoadProfile:
    """Declared, reproducible load profile for one bounded multi-worker run."""

    profile_id: str
    workers: int
    jobs: int
    partitions_per_job: int
    tenants: int
    lease_seconds: int

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be at least 1.")
        if self.jobs < 1:
            raise ValueError("jobs must be at least 1.")
        if self.partitions_per_job < 1:
            raise ValueError("partitions_per_job must be at least 1.")
        if self.tenants < 1 or self.tenants > self.jobs:
            raise ValueError("tenants must satisfy 1 <= tenants <= jobs.")
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1.")
        if self.workers % self.tenants != 0:
            raise ValueError("workers must be an exact multiple of tenants for fair per-tenant contention.")

    @property
    def declared_partition_effects(self) -> int:
        return self.jobs * self.partitions_per_job


@dataclass(frozen=True)
class DurableJobLoadResult:
    """Manifest of one bounded multi-worker load run."""

    schema_version: int
    profile_id: str
    workers: int
    jobs: int
    partitions_per_job: int
    tenants: int
    declared_partition_effects: int
    completed_jobs: int
    committed_partition_effects: int
    duplicate_partition_effects: int
    final_queue_depth: int
    final_running_depth: int
    observed_runtime_seconds: float
    observed_peak_memory_mb: float
    observed_throughput_jobs_per_second: float
    per_tenant_completions: dict[str, int]
    effect_set_digest: str
    manifest_digest: str
    environment: dict[str, object]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def default_profile(
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    workers: int = DEFAULT_WORKERS,
    jobs: int = DEFAULT_JOBS,
    partitions_per_job: int = DEFAULT_PARTITIONS_PER_JOB,
    tenants: int = DEFAULT_TENANTS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DurableJobLoadProfile:
    return DurableJobLoadProfile(
        profile_id=profile_id,
        workers=workers,
        jobs=jobs,
        partitions_per_job=partitions_per_job,
        tenants=tenants,
        lease_seconds=lease_seconds,
    )


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": int(os.cpu_count() or 1),
    }


def _utc_second(epoch_seconds: float) -> str:
    """Canonical whole-second UTC timestamp deterministically derived from a clock."""

    from datetime import UTC, datetime

    parsed = datetime.fromtimestamp(int(epoch_seconds), tz=UTC)
    return parsed.isoformat().replace("+00:00", "Z")


def _job_submission(job_id: str, key: str, tenant_id: str, total_units: int, created_at: str) -> JobSubmission:
    return JobSubmission(
        job_id=job_id,
        idempotency_scope=f"{tenant_id}/load-profile/{profile_scope(key)}",
        idempotency_key=key,
        tenant_id=tenant_id,
        workspace_id=f"{tenant_id}/ws-load",
        entity_id=f"{tenant_id}/entity-load",
        input_digest=hashlib.sha256(f"input:{job_id}".encode("ascii")).hexdigest(),
        config_digest=hashlib.sha256(f"config:{job_id}".encode("ascii")).hexdigest(),
        worker_version=WORKER_VERSION,
        total_units=total_units,
        retry_ceiling=2,
        created_at=created_at,
    )


def profile_scope(key: str) -> str:
    return hashlib.sha256(f"scope:{key}".encode("ascii")).hexdigest()


def _submit_all(
    *,
    application: DurableJobApplicationService,
    profile: DurableJobLoadProfile,
    submit_started_at: float,
) -> None:
    created_at = _utc_second(submit_started_at)
    for index in range(profile.jobs):
        tenant_index = index % profile.tenants
        tenant_id = _tenant_id(tenant_index)
        job_id = _job_id(index)
        key = f"key-{index:06d}"
        application.submit(
            _job_submission(job_id, key, tenant_id, profile.partitions_per_job, created_at),
            actor_id="load-submitter",
        )


def _tenant_id(tenant_index: int) -> str:
    return f"TENANT-{tenant_index:04d}"


def _job_id(index: int) -> str:
    return f"LOAD-JOB-{index:06d}"


def _worker_loop(
    *,
    worker_id: str,
    tenant_index: int,
    database_path: Path,
    profile: DurableJobLoadProfile,
    counters: dict[str, int],
    state_lock: threading.Lock,
    finish_event: threading.Event,
) -> None:
    tenant_id = _tenant_id(tenant_index)
    remaining = profile.jobs // profile.tenants
    handled = 0
    connection = connect(database_path, require_exists=True)
    try:
        repository = SQLiteDurableJobRepository(connection)
        worker = DurableJobWorkerService(repository)
        while not finish_event.is_set() and handled < remaining:
            claim_at = _utc_second(time.time())
            lease_expires = _utc_second(time.time() + profile.lease_seconds)
            claimed = worker.claim(
                tenant_id=tenant_id,
                worker_id=worker_id,
                occurred_at=claim_at,
                lease_expires_at=lease_expires,
            )
            if claimed is None:
                time.sleep(0.002)
                continue
            _drain_one_job(
                worker=worker,
                leased=claimed,
                profile=profile,
            )
            with state_lock:
                counters[tenant_id] = counters.get(tenant_id, 0) + 1
            handled += 1
    finally:
        connection.close()


def _drain_one_job(
    *,
    worker: DurableJobWorkerService,
    leased: LeasedJob,
    profile: DurableJobLoadProfile,
) -> None:
    job_id = leased.job.id
    partitions_done = len(worker.completed_effects(leased))
    while partitions_done < profile.partitions_per_job:
        ordinal = partitions_done + 1
        output = hashlib.sha256(f"{job_id}:out:{ordinal}".encode("ascii")).hexdigest()
        occurred_at = _utc_second(time.time() + ordinal)
        if ordinal < profile.partitions_per_job:
            leased = worker.commit_partition(
                leased,
                partition_key=f"partition/{ordinal:04d}",
                ordinal=ordinal,
                completed_units=ordinal,
                input_digest=hashlib.sha256(f"{job_id}:in:{ordinal}".encode("ascii")).hexdigest(),
                output_digest=output,
                effect_reference=f"effect/{job_id}/{ordinal:04d}",
                occurred_at=occurred_at,
            )
        else:
            manifest = JobOutputManifest(
                schema_version=1,
                digest=hashlib.sha256(f"{job_id}:manifest".encode("ascii")).hexdigest(),
                reference=f"manifest/{job_id}/v1",
            )
            worker.complete_partition(
                leased,
                partition_key=f"partition/{ordinal:04d}",
                ordinal=ordinal,
                input_digest=hashlib.sha256(f"{job_id}:in:{ordinal}".encode("ascii")).hexdigest(),
                output_digest=output,
                effect_reference=f"effect/{job_id}/{ordinal:04d}",
                occurred_at=occurred_at,
                output_manifest=manifest,
            )
        partitions_done = ordinal


def _effect_set_digest(connection: sqlite3.Connection, profile: DurableJobLoadProfile) -> tuple[str, int, dict[str, int]]:
    """Compute a deterministic digest over the committed partition-effect set."""

    rows: list[tuple[object, ...]] = []
    for index in range(profile.jobs):
        tenant_index = index % profile.tenants
        tenant_id = _tenant_id(tenant_index)
        job_id = _job_id(index)
        repository = SQLiteDurableJobRepository(connection)
        effects = repository.list_partition_effects(tenant_id=tenant_id, job_id=job_id)
        rows.extend(
            (
                effect.job_id,
                effect.partition_key,
                effect.ordinal,
                effect.input_digest,
                effect.output_digest,
                effect.effect_reference,
            )
            for effect in effects
        )
    serialized = json.dumps(
        {
            "schema_version": LOAD_PROFILE_SCHEMA_VERSION,
            "profile_id": profile.profile_id,
            "rows": [list(row) for row in sorted(rows)],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(serialized.encode("ascii")).hexdigest()
    by_job: dict[str, int] = {}
    for row in rows:
        job_id = str(row[0])
        by_job[job_id] = by_job.get(job_id, 0) + 1
    return digest, len(rows), by_job


def _final_depth(connection: sqlite3.Connection) -> tuple[int, int]:
    queued = connection.execute(
        "SELECT COUNT(*) FROM durable_jobs WHERE status IN ('queued','retrying')"
    ).fetchone()[0]
    running = connection.execute(
        "SELECT COUNT(*) FROM durable_jobs WHERE status='running'"
    ).fetchone()[0]
    return int(queued), int(running)


def _duplicate_count(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        """
        SELECT job_id, partition_key, COUNT(*) AS occurrences
        FROM durable_job_partition_effects
        GROUP BY job_id, partition_key
        HAVING occurrences > 1
        """
    ).fetchall()
    return int(sum(int(row[2]) - 1 for row in rows))


def _manifest_digest(document: dict[str, object]) -> str:
    stable = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "observed_runtime_seconds",
            "observed_peak_memory_mb",
            "observed_throughput_jobs_per_second",
            "manifest_digest",
        }
    }
    serialized = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("ascii")).hexdigest()


LIMITATIONS = (
    "Single shared SQLite database; writes serialize under BEGIN IMMEDIATE so measured contention bounds multi-worker coordination, not database partition parallelism.",
    "Observed runtime, peak memory, and throughput vary by hardware/load; they are capacity observations and are explicitly not a scale, soak, SLO, or sizing claim.",
    "The declared tier is small (8 workers, 64 jobs, 4 partitions per job, 4 tenants = 256 declared partition effects); 10K/100K/1M/10M scale tiers, backpressure, retry/backoff coupling, soak, and cancellation-under-load profiles remain later P4-SCL-001 slices.",
    "Workers are statically pinned to one tenant each so per-tenant contention is fair; cross-tenant claim sharing is not exercised.",
    "PostgreSQL load parity is not exercised by this local SQLite slice.",
)


def _limitations_for_profile(profile: DurableJobLoadProfile) -> tuple[str, ...]:
    """Keep the declared tier in the manifest's non-claim boundary."""

    if profile.profile_id == "durable-job-load/10k-tier-v1":
        return (
            LIMITATIONS[0],
            LIMITATIONS[1],
            "The declared tier is 10K (16 workers, 1,000 jobs, 10 partitions per job, 4 tenants = 10,000 committed partition effects); 100K/1M/10M tiers, backpressure, retry/backoff coupling, soak, cancellation-under-load, and PostgreSQL parity remain unverified.",
            LIMITATIONS[3],
            LIMITATIONS[4],
        )
    return LIMITATIONS


def run_durable_job_load_profile(
    database_path: Path,
    *,
    profile: DurableJobLoadProfile | None = None,
) -> DurableJobLoadResult:
    """Run one bounded multi-worker durable-job load profile and return its manifest."""

    declared = profile or default_profile()
    run_migrations(database_path)
    setup_connection = connect(database_path, require_exists=True)
    try:
        application = DurableJobApplicationService(SQLiteDurableJobRepository(setup_connection))
        submit_started = time.time()
        _submit_all(application=application, profile=declared, submit_started_at=submit_started)
    finally:
        setup_connection.close()

    tracemalloc.start()
    started = time.time()
    counters: dict[str, int] = {_tenant_id(t): 0 for t in range(declared.tenants)}
    state_lock = threading.Lock()
    finish_event = threading.Event()

    workers_per_tenant = declared.workers // declared.tenants
    worker_specs: list[tuple[str, int]] = []
    for tenant_index in range(declared.tenants):
        for slot in range(workers_per_tenant):
            worker_specs.append((f"load-worker-{tenant_index:02d}-{slot:02d}", tenant_index))

    with ThreadPoolExecutor(max_workers=declared.workers, thread_name_prefix="reconforge-load") as pool:
        futures = [
            pool.submit(
                _worker_loop,
                worker_id=worker_id,
                tenant_index=tenant_index,
                database_path=database_path,
                profile=declared,
                counters=counters,
                state_lock=state_lock,
                finish_event=finish_event,
            )
            for worker_id, tenant_index in worker_specs
        ]
        while True:
            time.sleep(0.005)
            handled = sum(counters.values())
            if handled >= declared.jobs:
                break
        finish_event.set()
        for future in futures:
            future.result()

    runtime = time.time() - started
    peak_current, _peak_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    audit_connection = connect(database_path, require_exists=True)
    try:
        final_queue, final_running = _final_depth(audit_connection)
        duplicate = _duplicate_count(audit_connection)
        effect_digest, committed_effects, _by_job = _effect_set_digest(audit_connection, declared)
    finally:
        audit_connection.close()

    completed_jobs = sum(counters.values())
    throughput = round(completed_jobs / runtime, 4) if runtime > 0 else 0.0
    per_tenant = dict(sorted(counters.items()))
    observed_runtime = round(runtime, 4)
    observed_peak_mb = round(peak_current / (1024 * 1024), 4)
    environment = _environment()
    limitations = _limitations_for_profile(declared)

    document: dict[str, object] = {
        "schema_version": LOAD_PROFILE_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "jobs": declared.jobs,
        "partitions_per_job": declared.partitions_per_job,
        "tenants": declared.tenants,
        "declared_partition_effects": declared.declared_partition_effects,
        "completed_jobs": completed_jobs,
        "committed_partition_effects": committed_effects,
        "duplicate_partition_effects": duplicate,
        "final_queue_depth": final_queue,
        "final_running_depth": final_running,
        "observed_runtime_seconds": observed_runtime,
        "observed_peak_memory_mb": observed_peak_mb,
        "observed_throughput_jobs_per_second": throughput,
        "per_tenant_completions": per_tenant,
        "effect_set_digest": effect_digest,
        "environment": environment,
        "limitations": list(limitations),
    }
    manifest_digest = _manifest_digest(document)
    return DurableJobLoadResult(
        schema_version=LOAD_PROFILE_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        jobs=declared.jobs,
        partitions_per_job=declared.partitions_per_job,
        tenants=declared.tenants,
        declared_partition_effects=declared.declared_partition_effects,
        completed_jobs=completed_jobs,
        committed_partition_effects=committed_effects,
        duplicate_partition_effects=duplicate,
        final_queue_depth=final_queue,
        final_running_depth=final_running,
        observed_runtime_seconds=observed_runtime,
        observed_peak_memory_mb=observed_peak_mb,
        observed_throughput_jobs_per_second=throughput,
        per_tenant_completions=per_tenant,
        effect_set_digest=effect_digest,
        manifest_digest=manifest_digest,
        environment=environment,
        limitations=limitations,
    )


def verify_load_manifest(result: DurableJobLoadResult, *, profile: DurableJobLoadProfile) -> None:
    """Assert the structural invariants the manifest claims to have proved."""

    if result.schema_version != LOAD_PROFILE_SCHEMA_VERSION:
        raise AssertionError("load manifest schema_version is not v1.")
    if result.profile_id != profile.profile_id:
        raise AssertionError("load manifest profile_id does not match the declared profile.")
    if result.workers != profile.workers or result.jobs != profile.jobs:
        raise AssertionError("load manifest declared shape does not match the profile.")
    if result.partitions_per_job != profile.partitions_per_job or result.tenants != profile.tenants:
        raise AssertionError("load manifest declared shape does not match the profile.")
    if result.declared_partition_effects != profile.declared_partition_effects:
        raise AssertionError("declared_partition_effects mismatch.")
    if result.completed_jobs != profile.jobs:
        raise AssertionError("completed jobs must equal the declared job count.")
    if result.duplicate_partition_effects != 0:
        raise AssertionError("duplicate partition effects were observed under contention.")
    if result.final_queue_depth != 0 or result.final_running_depth != 0:
        raise AssertionError("queue did not drain to zero.")
    if result.committed_partition_effects != result.completed_jobs * profile.partitions_per_job:
        raise AssertionError("committed partition effects do not equal completed_jobs * partitions.")
    if sum(result.per_tenant_completions.values()) != profile.jobs:
        raise AssertionError("per-tenant completions must sum to the declared job count.")
    if not result.effect_set_digest:
        raise AssertionError("effect_set_digest is missing.")
    if not result.manifest_digest:
        raise AssertionError("manifest_digest is missing.")
    if not result.limitations:
        raise AssertionError("load manifest must declare its limitations.")
    non_claim_markers = ("not a", "not exercised", "remain", "are explicitly not", "not database")
    if not all(any(marker in item for marker in non_claim_markers) for item in result.limitations):
        raise AssertionError("load manifest limitations must retain honest non-claim wording.")
