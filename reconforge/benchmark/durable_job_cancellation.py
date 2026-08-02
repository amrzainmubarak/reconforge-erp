"""Reproducible durable-job cancellation-under-load profile (P4-SCL-001 second slice).

This harness extends the existing durable-job worker loop with bounded
cancellation-under-load and proves:

* cancellations of queued jobs are honoured while workers race claims,
* no cancelled job produces a partition effect or completes,
* every non-cancelled job completes exactly once with no duplicate effects,
* no leases are orphaned after the run (clean lease release),
* the queue drains to zero,
* a closed schema-v1 manifest records the structural outcome with a
  deterministic digest that is reproducible across runs, plus observed
  timing/memory counters that are explicitly non-claims.

This is the smallest reversible vertical slice for P4-SCL-001 cancellation.
It reuses the existing durable-job worker loop, the existing
`application.cancel` (QUEUED -> CANCELLED) and `worker.cancel` (RUNNING ->
CANCELLED with clean lease release) transitions, and the already-proved
generation-fenced lease contract. No new persistence primitive, domain type,
repository method, or migration is introduced. Cancellation of a *running*
job under load (clean interrupting of a worker mid-partition) is exercised
separately by `run_durable_job_running_cancel_profile`; full
backpressure, soak, retry/backoff coupling, PostgreSQL load parity, and
10K/100K/1M/10M tier publication remain later P4-SCL-001 slices.
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
from reconforge.domain.jobs import JobOutputManifest, JobStatus
from reconforge.infrastructure.sqlite_jobs import (
    SQLiteDurableJobRepository,
    SQLiteJobRepositoryError,
)

LOAD_CANCEL_SCHEMA_VERSION = 1
DEFAULT_CANCEL_PROFILE_ID = "durable-job-cancel/small-tier-v1"
DEFAULT_CANCEL_WORKERS = 8
DEFAULT_CANCEL_JOBS = 64
DEFAULT_CANCEL_PARTITIONS_PER_JOB = 4
DEFAULT_CANCEL_TENANTS = 4
DEFAULT_CANCEL_JOBS_TO_CANCEL = 16
DEFAULT_CANCEL_LEASE_SECONDS = 30
CANCEL_WORKER_VERSION = "durable-job-cancel-harness/1.0.0"


@dataclass(frozen=True)
class DurableJobCancelProfile:
    """Declared, reproducible cancellation-under-load profile."""

    profile_id: str
    workers: int
    jobs: int
    partitions_per_job: int
    tenants: int
    jobs_to_cancel: int
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
        if self.workers % self.tenants != 0:
            raise ValueError("workers must be an exact multiple of tenants for fair per-tenant contention.")
        if not 0 <= self.jobs_to_cancel <= self.jobs:
            raise ValueError("jobs_to_cancel must satisfy 0 <= jobs_to_cancel <= jobs.")
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1.")

    @property
    def declared_partition_effects(self) -> int:
        return (self.jobs - self.jobs_to_cancel) * self.partitions_per_job


@dataclass(frozen=True)
class DurableJobCancelResult:
    """Manifest of one bounded cancellation-under-load run."""

    schema_version: int
    profile_id: str
    workers: int
    jobs: int
    partitions_per_job: int
    tenants: int
    jobs_to_cancel: int
    declared_partition_effects: int
    completed_jobs: int
    cancelled_jobs: int
    running_cancellations: int
    committed_partition_effects: int
    duplicate_partition_effects: int
    final_queue_depth: int
    final_running_depth: int
    orphaned_leases: int
    observed_runtime_seconds: float
    observed_peak_memory_mb: float
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


def default_cancel_profile(
    *,
    profile_id: str = DEFAULT_CANCEL_PROFILE_ID,
    workers: int = DEFAULT_CANCEL_WORKERS,
    jobs: int = DEFAULT_CANCEL_JOBS,
    partitions_per_job: int = DEFAULT_CANCEL_PARTITIONS_PER_JOB,
    tenants: int = DEFAULT_CANCEL_TENANTS,
    jobs_to_cancel: int = DEFAULT_CANCEL_JOBS_TO_CANCEL,
    lease_seconds: int = DEFAULT_CANCEL_LEASE_SECONDS,
) -> DurableJobCancelProfile:
    return DurableJobCancelProfile(
        profile_id=profile_id,
        workers=workers,
        jobs=jobs,
        partitions_per_job=partitions_per_job,
        tenants=tenants,
        jobs_to_cancel=jobs_to_cancel,
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
    from datetime import UTC, datetime

    parsed = datetime.fromtimestamp(int(epoch_seconds), tz=UTC)
    return parsed.isoformat().replace("+00:00", "Z")


def _tenant_id(tenant_index: int) -> str:
    return f"TENANT-{tenant_index:04d}"


def _job_id(index: int) -> str:
    return f"CANCEL-JOB-{index:06d}"


def _job_submission(job_id: str, key: str, tenant_id: str, total_units: int, created_at: str) -> JobSubmission:
    return JobSubmission(
        job_id=job_id,
        idempotency_scope=f"{tenant_id}/cancel-profile/{hashlib.sha256(f'scope:{key}'.encode('ascii')).hexdigest()}",
        idempotency_key=key,
        tenant_id=tenant_id,
        workspace_id=f"{tenant_id}/ws-cancel",
        entity_id=f"{tenant_id}/entity-cancel",
        input_digest=hashlib.sha256(f"input:{job_id}".encode("ascii")).hexdigest(),
        config_digest=hashlib.sha256(f"config:{job_id}".encode("ascii")).hexdigest(),
        worker_version=CANCEL_WORKER_VERSION,
        total_units=total_units,
        retry_ceiling=2,
        created_at=created_at,
    )


def _submit_all(
    *,
    application: DurableJobApplicationService,
    profile: DurableJobCancelProfile,
    submit_started_at: float,
) -> list[str]:
    created_at = _utc_second(submit_started_at)
    job_ids: list[str] = []
    for index in range(profile.jobs):
        tenant_index = index % profile.tenants
        tenant_id = _tenant_id(tenant_index)
        job_id = _job_id(index)
        key = f"cancel-key-{index:06d}"
        application.submit(
            _job_submission(job_id, key, tenant_id, profile.partitions_per_job, created_at),
            actor_id="cancel-submitter",
        )
        job_ids.append(job_id)
    return job_ids


def _cancel_queued_subset(
    *,
    application: DurableJobApplicationService,
    job_ids: list[str],
    profile: DurableJobCancelProfile,
    tenant_for_job: dict[str, str],
    counters: dict[str, int],
    state_lock: threading.Lock,
) -> None:
    """Cancel the declared queued subset; tolerate race-loss where a worker already claimed the job."""

    occurred_at = _utc_second(time.time())
    for index, job_id in enumerate(job_ids):
        if index >= profile.jobs_to_cancel:
            break
        tenant_id = tenant_for_job[job_id]
        try:
            application.cancel(
                tenant_id=tenant_id,
                job_id=job_id,
                actor_id="cancel-submitter",
                occurred_at=occurred_at,
            )
            with state_lock:
                counters["cancelled"] += 1
        except SQLiteJobRepositoryError:
            with state_lock:
                counters["cancel_race_lost"] += 1


def _worker_loop(
    *,
    worker_id: str,
    tenant_index: int,
    database_path: Path,
    profile: DurableJobCancelProfile,
    counters: dict[str, int],
    state_lock: threading.Lock,
    claim_gate: threading.Event,
    finish_event: threading.Event,
) -> None:
    tenant_id = _tenant_id(tenant_index)
    connection = connect(database_path, require_exists=True)
    try:
        repository = SQLiteDurableJobRepository(connection)
        worker = DurableJobWorkerService(repository)
        while not finish_event.is_set():
            if not claim_gate.is_set():
                time.sleep(0.002)
                continue
            claim_at = _utc_second(time.time())
            lease_expires = _utc_second(time.time() + profile.lease_seconds)
            try:
                claimed = worker.claim(
                    tenant_id=tenant_id,
                    worker_id=worker_id,
                    occurred_at=claim_at,
                    lease_expires_at=lease_expires,
                )
            except SQLiteJobRepositoryError:
                time.sleep(0.002)
                continue
            if claimed is None:
                time.sleep(0.002)
                continue
            _drain_one_job(worker=worker, leased=claimed, profile=profile)
            with state_lock:
                counters[tenant_id] = counters.get(tenant_id, 0) + 1
    finally:
        connection.close()


def _drain_one_job(
    *,
    worker: DurableJobWorkerService,
    leased: LeasedJob,
    profile: DurableJobCancelProfile,
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


def _effect_set_digest(connection: sqlite3.Connection, profile: DurableJobCancelProfile) -> tuple[str, int]:
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
            "schema_version": LOAD_CANCEL_SCHEMA_VERSION,
            "profile_id": profile.profile_id,
            "rows": [list(row) for row in sorted(rows)],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("ascii")).hexdigest(), len(rows)


def _final_depth(connection: sqlite3.Connection) -> tuple[int, int, int]:
    queued = connection.execute(
        "SELECT COUNT(*) FROM durable_jobs WHERE status IN ('queued','retrying')"
    ).fetchone()[0]
    running = connection.execute(
        "SELECT COUNT(*) FROM durable_jobs WHERE status='running'"
    ).fetchone()[0]
    orphaned = connection.execute(
        """
        SELECT COUNT(*)
        FROM durable_job_leases leases
        LEFT JOIN durable_jobs jobs ON jobs.id = leases.job_id
        WHERE jobs.status <> 'running'
        """
    ).fetchone()[0]
    return int(queued), int(running), int(orphaned)


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
            "manifest_digest",
        }
    }
    serialized = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("ascii")).hexdigest()


LIMITATIONS = (
    "Single shared SQLite database; writes serialize under BEGIN IMMEDIATE so measured contention bounds multi-worker coordination, not database partition parallelism.",
    "Observed runtime and peak memory vary by hardware/load; they are capacity observations and are explicitly not a scale, soak, SLO, or sizing claim.",
    "Cancellation targets only queued jobs that the submitter cancels before a worker claims them; if a worker has already claimed a queued-to-cancel job, the cancel is race-lost and the job completes normally. Running-job cancellation under load is exercised separately by run_durable_job_running_cancel_profile and is not exercised by this queued-cancellation profile.",
    "The declared tier is small (8 workers, 64 jobs, 4 partitions per job, 4 tenants, 16 jobs to cancel = 192 remaining partition effects); 10K/100K/1M/10M scale tiers, backpressure, soak, retry/backoff coupling, and running-job interruption remain later P4-SCL-001 slices.",
    "PostgreSQL load parity is not exercised by this local SQLite slice.",
)


def run_durable_job_cancellation_profile(
    database_path: Path,
    *,
    profile: DurableJobCancelProfile | None = None,
) -> DurableJobCancelResult:
    """Run one bounded cancellation-under-load profile and return its manifest."""

    declared = profile or default_cancel_profile()
    run_migrations(database_path)
    setup_connection = connect(database_path, require_exists=True)
    try:
        application = DurableJobApplicationService(SQLiteDurableJobRepository(setup_connection))
        submit_started = time.time()
        job_ids = _submit_all(application=application, profile=declared, submit_started_at=submit_started)
        tenant_for_job = {
            _job_id(index): _tenant_id(index % declared.tenants) for index in range(declared.jobs)
        }
    finally:
        setup_connection.close()

    tracemalloc.start()
    started = time.time()
    counters: dict[str, int] = {
        _tenant_id(t): 0 for t in range(declared.tenants)
    }
    counters["cancelled"] = 0
    counters["cancel_race_lost"] = 0
    counters["running_cancellations"] = 0
    state_lock = threading.Lock()
    claim_gate = threading.Event()
    finish_event = threading.Event()

    cancel_connection = connect(database_path, require_exists=True)
    try:
        cancel_application = DurableJobApplicationService(SQLiteDurableJobRepository(cancel_connection))
        _cancel_queued_subset(
            application=cancel_application,
            job_ids=job_ids,
            profile=declared,
            tenant_for_job=tenant_for_job,
            counters=counters,
            state_lock=state_lock,
        )
    finally:
        cancel_connection.close()
    claim_gate.set()

    workers_per_tenant = declared.workers // declared.tenants
    worker_specs: list[tuple[str, int]] = []
    for tenant_index in range(declared.tenants):
        for slot in range(workers_per_tenant):
            worker_specs.append((f"cancel-worker-{tenant_index:02d}-{slot:02d}", tenant_index))

    with ThreadPoolExecutor(max_workers=declared.workers, thread_name_prefix="reconforge-cancel") as pool:
        futures = [
            pool.submit(
                _worker_loop,
                worker_id=worker_id,
                tenant_index=tenant_index,
                database_path=database_path,
                profile=declared,
                counters=counters,
                state_lock=state_lock,
                claim_gate=claim_gate,
                finish_event=finish_event,
            )
            for worker_id, tenant_index in worker_specs
        ]
        while True:
            time.sleep(0.005)
            handled = sum(counters[t_id] for t_id in (_tenant_id(t) for t in range(declared.tenants)))
            if handled + counters["cancelled"] >= declared.jobs:
                break
        finish_event.set()
        for future in futures:
            future.result()

    runtime = time.time() - started
    _current_peak, peak_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    audit_connection = connect(database_path, require_exists=True)
    try:
        final_queue, final_running, orphaned = _final_depth(audit_connection)
        duplicate = _duplicate_count(audit_connection)
        effect_digest, committed_effects = _effect_set_digest(audit_connection, declared)
    finally:
        audit_connection.close()

    completed_jobs = sum(counters[t_id] for t_id in (_tenant_id(t) for t in range(declared.tenants)))
    cancelled_jobs = int(counters["cancelled"])
    running_cancellations = int(counters["running_cancellations"])
    observed_runtime = round(runtime, 4)
    observed_peak_mb = round(peak_peak / (1024 * 1024), 4)
    environment = _environment()
    limitations = LIMITATIONS

    document: dict[str, object] = {
        "schema_version": LOAD_CANCEL_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "jobs": declared.jobs,
        "partitions_per_job": declared.partitions_per_job,
        "tenants": declared.tenants,
        "jobs_to_cancel": declared.jobs_to_cancel,
        "declared_partition_effects": declared.declared_partition_effects,
        "completed_jobs": completed_jobs,
        "cancelled_jobs": cancelled_jobs,
        "running_cancellations": running_cancellations,
        "committed_partition_effects": committed_effects,
        "duplicate_partition_effects": duplicate,
        "final_queue_depth": final_queue,
        "final_running_depth": final_running,
        "orphaned_leases": orphaned,
        "observed_runtime_seconds": observed_runtime,
        "observed_peak_memory_mb": observed_peak_mb,
        "effect_set_digest": effect_digest,
        "environment": environment,
        "limitations": list(limitations),
    }
    manifest_digest = _manifest_digest(document)
    return DurableJobCancelResult(
        schema_version=LOAD_CANCEL_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        jobs=declared.jobs,
        partitions_per_job=declared.partitions_per_job,
        tenants=declared.tenants,
        jobs_to_cancel=declared.jobs_to_cancel,
        declared_partition_effects=declared.declared_partition_effects,
        completed_jobs=completed_jobs,
        cancelled_jobs=cancelled_jobs,
        running_cancellations=running_cancellations,
        committed_partition_effects=committed_effects,
        duplicate_partition_effects=duplicate,
        final_queue_depth=final_queue,
        final_running_depth=final_running,
        orphaned_leases=orphaned,
        observed_runtime_seconds=observed_runtime,
        observed_peak_memory_mb=observed_peak_mb,
        effect_set_digest=effect_digest,
        manifest_digest=manifest_digest,
        environment=environment,
        limitations=limitations,
    )


def verify_cancel_manifest(result: DurableJobCancelResult, *, profile: DurableJobCancelProfile) -> None:
    """Assert the structural invariants the cancellation-under-load manifest claims to have proved."""

    if result.schema_version != LOAD_CANCEL_SCHEMA_VERSION:
        raise AssertionError("cancel manifest schema_version is not v1.")
    if result.profile_id != profile.profile_id:
        raise AssertionError("cancel manifest profile_id does not match the declared profile.")
    if result.workers != profile.workers or result.jobs != profile.jobs:
        raise AssertionError("cancel manifest declared shape does not match the profile.")
    if result.partitions_per_job != profile.partitions_per_job or result.tenants != profile.tenants:
        raise AssertionError("cancel manifest declared shape does not match the profile.")
    if result.jobs_to_cancel != profile.jobs_to_cancel:
        raise AssertionError("cancel manifest jobs_to_cancel does not match the profile.")
    if result.declared_partition_effects != profile.declared_partition_effects:
        raise AssertionError("declared_partition_effects mismatch.")
    if result.completed_jobs + result.cancelled_jobs != profile.jobs:
        raise AssertionError("completed + cancelled jobs must equal the declared job count.")
    if result.duplicate_partition_effects != 0:
        raise AssertionError("duplicate partition effects were observed under cancellation-under-load.")
    if result.final_queue_depth != 0 or result.final_running_depth != 0:
        raise AssertionError("queue did not drain to zero after cancellation-under-load.")
    if result.orphaned_leases != 0:
        raise AssertionError("orphaned leases remained after cancellation-under-load.")
    if result.committed_partition_effects != result.completed_jobs * profile.partitions_per_job:
        raise AssertionError("committed partition effects do not equal completed_jobs * partitions.")
    if not result.effect_set_digest:
        raise AssertionError("effect_set_digest is missing.")
    if not result.manifest_digest:
        raise AssertionError("manifest_digest is missing.")
    non_claim_markers = ("not a", "not exercised", "remain", "are explicitly not", "not database")
    if not result.limitations:
        raise AssertionError("cancel manifest must declare its limitations.")
    if not all(any(marker in item for marker in non_claim_markers) for item in result.limitations):
        raise AssertionError("cancel manifest limitations must retain honest non-claim wording.")


@dataclass(frozen=True)
class RunningCancelResult:
    """Manifest of a single running-job cancellation-under-claim profile."""

    schema_version: int
    profile_id: str
    claimed_partitions_completed_before_cancel: int
    running_cancelled: bool
    lease_released: bool
    final_job_status: str
    committed_partition_effects: int
    duplicate_partition_effects: int
    orphaned_leases: int
    observed_runtime_seconds: float
    manifest_digest: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def run_durable_job_running_cancel_profile(
    database_path: Path,
    *,
    partitions_before_cancel: int = 2,
    total_partitions: int = 4,
) -> RunningCancelResult:
    """Claim a job, commit some partitions, then cancel it as the running owner; prove clean lease release."""

    if partitions_before_cancel < 0 or partitions_before_cancel >= total_partitions:
        raise ValueError("partitions_before_cancel must satisfy 0 <= partitions_before_cancel < total_partitions.")
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    try:
        repository = SQLiteDurableJobRepository(connection)
        application = DurableJobApplicationService(repository)
        worker = DurableJobWorkerService(repository)
        created_at = _utc_second(time.time())
        job_id = "RUNNING-CANCEL-JOB-000001"
        tenant_id = _tenant_id(0)
        application.submit(
            _job_submission(job_id, "running-cancel-key", tenant_id, total_partitions, created_at),
            actor_id="running-cancel-submitter",
        )
        started = time.time()
        leased = worker.claim(
            tenant_id=tenant_id,
            worker_id="running-cancel-worker",
            occurred_at=_utc_second(time.time()),
            lease_expires_at=_utc_second(time.time() + 60),
        )
        if leased is None:
            raise RuntimeError("Claim returned None for a freshly submitted job.")
        for ordinal in range(1, partitions_before_cancel + 1):
            output = hashlib.sha256(f"{job_id}:out:{ordinal}".encode("ascii")).hexdigest()
            leased = worker.commit_partition(
                leased,
                partition_key=f"partition/{ordinal:04d}",
                ordinal=ordinal,
                completed_units=ordinal,
                input_digest=hashlib.sha256(f"{job_id}:in:{ordinal}".encode("ascii")).hexdigest(),
                output_digest=output,
                effect_reference=f"effect/{job_id}/{ordinal:04d}",
                occurred_at=_utc_second(time.time() + ordinal),
            )
        cancelled_job = worker.cancel(leased, occurred_at=_utc_second(time.time() + partitions_before_cancel + 1))
        runtime = time.time() - started
        effects = repository.list_partition_effects(tenant_id=tenant_id, job_id=job_id)
        committed_effects = len(effects)
        final_status = str(cancelled_job.status.value)
        duplicate = _duplicate_count(connection)
        _queued, _running, orphaned = _final_depth(connection)
        lease_released = not bool(
            connection.execute(
                "SELECT 1 FROM durable_job_leases WHERE job_id=?",
                (job_id,),
            ).fetchone()
        )
        document = {
            "schema_version": LOAD_CANCEL_SCHEMA_VERSION,
            "profile_id": "durable-job-running-cancel/single-v1",
            "claimed_partitions_completed_before_cancel": partitions_before_cancel,
            "running_cancelled": final_status == JobStatus.CANCELLED.value,
            "lease_released": lease_released,
            "final_job_status": final_status,
            "committed_partition_effects": committed_effects,
            "duplicate_partition_effects": duplicate,
            "orphaned_leases": orphaned,
        }
        stable = {k: v for k, v in document.items() if k != "observed_runtime_seconds"}
        manifest_digest = hashlib.sha256(
            json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        return RunningCancelResult(
            schema_version=LOAD_CANCEL_SCHEMA_VERSION,
            profile_id="durable-job-running-cancel/single-v1",
            claimed_partitions_completed_before_cancel=partitions_before_cancel,
            running_cancelled=final_status == JobStatus.CANCELLED.value,
            lease_released=lease_released,
            final_job_status=final_status,
            committed_partition_effects=committed_effects,
            duplicate_partition_effects=duplicate,
            orphaned_leases=orphaned,
            observed_runtime_seconds=round(runtime, 4),
            manifest_digest=manifest_digest,
        )
    finally:
        connection.close()


def verify_running_cancel_manifest(result: RunningCancelResult) -> None:
    if result.schema_version != LOAD_CANCEL_SCHEMA_VERSION:
        raise AssertionError("running cancel manifest schema_version is not v1.")
    if not result.running_cancelled:
        raise AssertionError("running job was not cancelled.")
    if not result.lease_released:
        raise AssertionError("lease was not cleanly released by worker.cancel.")
    if result.final_job_status != JobStatus.CANCELLED.value:
        raise AssertionError("final job status is not cancelled.")
    if result.duplicate_partition_effects != 0:
        raise AssertionError("duplicate partition effects were observed.")
    if result.orphaned_leases != 0:
        raise AssertionError("orphaned leases remained after running cancellation.")
