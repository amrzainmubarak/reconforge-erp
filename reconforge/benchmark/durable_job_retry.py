"""Bounded durable-job retry and failure-injection profile.

This profile exercises the existing generation-fenced worker lifecycle under
real thread contention. A synthetic transient fault is injected after the
first committed partition of selected jobs; the retry must resume from the
checkpoint and may not duplicate the already committed effect. The manifest
records structural evidence only and explicitly claims no provider-managed
backoff, PostgreSQL capacity, or a published scale tier.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sqlite3
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
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

RETRY_PROFILE_SCHEMA_VERSION = 1
DEFAULT_RETRY_PROFILE_ID = "durable-job-retry/small-tier-v1"
DEFAULT_RETRY_WORKERS = 4
DEFAULT_RETRY_JOBS = 16
DEFAULT_RETRY_PARTITIONS = 3
DEFAULT_RETRY_TENANTS = 2
DEFAULT_TRANSIENT_FAILURES = 1
DEFAULT_RETRY_CEILING = 2
DEFAULT_LEASE_SECONDS = 30
DEFAULT_RETRY_BACKOFF_BASE_SECONDS = 0.005
DEFAULT_RETRY_BACKOFF_MAX_SECONDS = 0.04
RETRY_WORKER_VERSION = "durable-job-retry-harness/1.0.0"


@dataclass(frozen=True)
class DurableJobRetryProfile:
    """Declared bounded retry profile."""

    profile_id: str
    workers: int
    jobs: int
    partitions_per_job: int
    tenants: int
    transient_failures_per_job: int
    retry_ceiling: int
    lease_seconds: int
    retry_backoff_base_seconds: float = DEFAULT_RETRY_BACKOFF_BASE_SECONDS
    retry_backoff_max_seconds: float = DEFAULT_RETRY_BACKOFF_MAX_SECONDS

    def __post_init__(self) -> None:
        if not self.profile_id or len(self.profile_id) > 160:
            raise ValueError("profile_id must be a bounded non-empty value.")
        if self.workers < 1 or self.jobs < 1 or self.partitions_per_job < 1:
            raise ValueError("workers, jobs, and partitions_per_job must be positive.")
        if self.tenants < 1 or self.tenants > self.jobs:
            raise ValueError("tenants must satisfy 1 <= tenants <= jobs.")
        if self.workers % self.tenants != 0:
            raise ValueError("workers must be an exact multiple of tenants.")
        if not 0 <= self.transient_failures_per_job <= self.retry_ceiling:
            raise ValueError("transient_failures_per_job must fit within retry_ceiling.")
        if self.retry_ceiling < 0 or self.lease_seconds < 1:
            raise ValueError("retry_ceiling must be non-negative and lease_seconds positive.")
        if self.retry_backoff_base_seconds < 0:
            raise ValueError("retry_backoff_base_seconds must be non-negative.")
        if self.retry_backoff_max_seconds < self.retry_backoff_base_seconds:
            raise ValueError("retry_backoff_max_seconds must be >= retry_backoff_base_seconds.")

    @property
    def declared_partition_effects(self) -> int:
        return self.jobs * self.partitions_per_job


@dataclass(frozen=True)
class DurableJobRetryResult:
    """Closed structural result of one retry run."""

    schema_version: int
    profile_id: str
    workers: int
    jobs: int
    partitions_per_job: int
    tenants: int
    transient_failures_per_job: int
    retry_ceiling: int
    declared_partition_effects: int
    completed_jobs: int
    failed_jobs: int
    scheduled_retries: int
    committed_partition_effects: int
    duplicate_partition_effects: int
    final_queue_depth: int
    final_running_depth: int
    max_retry_count: int
    effect_set_digest: str
    manifest_digest: str
    environment: dict[str, object]
    retry_delay_samples: tuple[float, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def default_retry_profile(
    *,
    profile_id: str = DEFAULT_RETRY_PROFILE_ID,
    workers: int = DEFAULT_RETRY_WORKERS,
    jobs: int = DEFAULT_RETRY_JOBS,
    partitions_per_job: int = DEFAULT_RETRY_PARTITIONS,
    tenants: int = DEFAULT_RETRY_TENANTS,
    transient_failures_per_job: int = DEFAULT_TRANSIENT_FAILURES,
    retry_ceiling: int = DEFAULT_RETRY_CEILING,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    retry_backoff_base_seconds: float = DEFAULT_RETRY_BACKOFF_BASE_SECONDS,
    retry_backoff_max_seconds: float = DEFAULT_RETRY_BACKOFF_MAX_SECONDS,
) -> DurableJobRetryProfile:
    return DurableJobRetryProfile(
        profile_id=profile_id,
        workers=workers,
        jobs=jobs,
        partitions_per_job=partitions_per_job,
        tenants=tenants,
        transient_failures_per_job=transient_failures_per_job,
        retry_ceiling=retry_ceiling,
        lease_seconds=lease_seconds,
        retry_backoff_base_seconds=retry_backoff_base_seconds,
        retry_backoff_max_seconds=retry_backoff_max_seconds,
    )


def _utc_second(epoch_seconds: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(int(epoch_seconds), tz=UTC).isoformat().replace("+00:00", "Z")


def _tenant_id(index: int) -> str:
    return f"TENANT-{index:04d}"


def _job_id(index: int) -> str:
    return f"RETRY-JOB-{index:06d}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _submission(index: int, profile: DurableJobRetryProfile, created_at: str) -> JobSubmission:
    tenant = _tenant_id(index % profile.tenants)
    job_id = _job_id(index)
    return JobSubmission(
        job_id=job_id,
        idempotency_scope=f"{tenant}/retry-profile",
        idempotency_key=f"retry-key-{index:06d}",
        tenant_id=tenant,
        workspace_id=f"{tenant}/ws-retry",
        entity_id=f"{tenant}/entity-retry",
        input_digest=_digest(f"input:{job_id}"),
        config_digest=_digest(f"config:{profile.profile_id}"),
        worker_version=RETRY_WORKER_VERSION,
        total_units=profile.partitions_per_job,
        retry_ceiling=profile.retry_ceiling,
        created_at=created_at,
    )


def _commit_partition(worker: DurableJobWorkerService, leased: LeasedJob, ordinal: int, now: str) -> LeasedJob:
    job_id = leased.job.id
    return worker.commit_partition(
        leased,
        partition_key=f"partition/{ordinal:04d}",
        ordinal=ordinal,
        completed_units=ordinal,
        input_digest=_digest(f"{job_id}:input:{ordinal}"),
        output_digest=_digest(f"{job_id}:output:{ordinal}"),
        effect_reference=f"effect/{job_id}/{ordinal:04d}",
        occurred_at=now,
    )


def _complete_partition(
    worker: DurableJobWorkerService, leased: LeasedJob, ordinal: int, now: str, profile: DurableJobRetryProfile
) -> None:
    job_id = leased.job.id
    worker.complete_partition(
        leased,
        partition_key=f"partition/{ordinal:04d}",
        ordinal=ordinal,
        input_digest=_digest(f"{job_id}:input:{ordinal}"),
        output_digest=_digest(f"{job_id}:output:{ordinal}"),
        effect_reference=f"effect/{job_id}/{ordinal:04d}",
        occurred_at=now,
        output_manifest=JobOutputManifest(
            schema_version=1,
            digest=_digest(f"{job_id}:manifest"),
            reference=f"manifest/{job_id}/v1",
        ),
    )


def _retry_delay(profile: DurableJobRetryProfile, attempt: int) -> float:
    if attempt < 0:
        raise ValueError("retry attempt cannot be negative.")
    return min(profile.retry_backoff_max_seconds, profile.retry_backoff_base_seconds * (2**min(attempt, 16)))


def _process_claim(
    worker: DurableJobWorkerService,
    leased: LeasedJob,
    profile: DurableJobRetryProfile,
    attempts: dict[str, int],
    attempts_lock: threading.Lock,
    now_fn: Callable[[], str],
    sleep_fn: Callable[[float], None],
    retry_delay_samples: list[float],
    retry_samples_lock: threading.Lock,
) -> tuple[str, int]:
    job_id = leased.job.id
    with attempts_lock:
        attempt = attempts.get(job_id, 0)
        attempts[job_id] = attempt + 1
    completed = {effect.ordinal for effect in worker.completed_effects(leased)}
    if attempt < profile.transient_failures_per_job:
        if not completed and profile.partitions_per_job > 1:
            leased = _commit_partition(worker, leased, 1, now_fn())
        delay = _retry_delay(profile, attempt)
        with retry_samples_lock:
            retry_delay_samples.append(delay)
        if delay > 0:
            sleep_fn(delay)
        worker.schedule_retry(leased, occurred_at=now_fn())
        return "retry", attempt + 1
    for ordinal in range(1, profile.partitions_per_job + 1):
        if ordinal in completed:
            continue
        if ordinal == profile.partitions_per_job:
            _complete_partition(worker, leased, ordinal, now_fn(), profile)
            break
        leased = _commit_partition(worker, leased, ordinal, now_fn())
    return "completed", attempt + 1


def _worker_loop(
    worker_id: str,
    tenant_index: int,
    database_path: Path,
    profile: DurableJobRetryProfile,
    attempts: dict[str, int],
    attempts_lock: threading.Lock,
    counters: dict[str, int],
    counters_lock: threading.Lock,
    finished: threading.Event,
    sleep_fn: Callable[[float], None],
    retry_delay_samples: list[float],
    retry_samples_lock: threading.Lock,
    clock_state: dict[str, int],
    clock_lock: threading.Lock,
) -> None:
    tenant_id = _tenant_id(tenant_index)
    connection = connect(database_path, require_exists=True)
    worker = DurableJobWorkerService(SQLiteDurableJobRepository(connection))
    try:
        while not finished.is_set():
            with clock_lock:
                clock_state["value"] += 1
                occurred_epoch = clock_state["value"]
            claimed = worker.claim(
                tenant_id=tenant_id,
                worker_id=worker_id,
                occurred_at=_utc_second(occurred_epoch),
                lease_expires_at=_utc_second(occurred_epoch + profile.lease_seconds),
            )
            if claimed is None:
                time.sleep(0.002)
                continue
            def next_now() -> str:
                with clock_lock:
                    clock_state["value"] += 1
                    return _utc_second(clock_state["value"])

            outcome, _attempt = _process_claim(
                worker=worker,
                leased=claimed,
                profile=profile,
                attempts=attempts,
                attempts_lock=attempts_lock,
                now_fn=next_now,
                sleep_fn=sleep_fn,
                retry_delay_samples=retry_delay_samples,
                retry_samples_lock=retry_samples_lock,
            )
            with counters_lock:
                counters[outcome] = counters.get(outcome, 0) + 1
                if counters.get("completed", 0) + counters.get("failed", 0) >= profile.jobs:
                    finished.set()
    finally:
        connection.close()


def _effect_digest(connection: sqlite3.Connection) -> tuple[str, int, int]:
    rows = connection.execute(
        "SELECT job_id, partition_key, ordinal, input_digest, output_digest, effect_reference "
        "FROM durable_job_partition_effects ORDER BY job_id, ordinal"
    ).fetchall()
    serialized = json.dumps([list(row) for row in rows], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    duplicate_rows = connection.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT job_id || ':' || partition_key) FROM durable_job_partition_effects"
    ).fetchone()[0]
    return _digest(serialized), len(rows), int(duplicate_rows)


def _manifest_digest(document: dict[str, object]) -> str:
    stable = {key: value for key, value in document.items() if key != "manifest_digest"}
    return _digest(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


LIMITATIONS = (
    "Synthetic transient faults run on one shared SQLite database; PostgreSQL retry/load parity is not exercised.",
    "Retrying uses bounded local exponential backoff in this harness only; provider-managed exponential backoff/jitter and tenant-scope fleet policy are not claimed.",
    "The declared tier is small and is not a 10K/100K/1M/10M scale, soak, or SLO claim.",
    "Fault injection occurs after at most one committed partition; external side-effect compensation is not exercised.",
)


def run_durable_job_retry_profile(
    database_path: Path,
    *,
    profile: DurableJobRetryProfile | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DurableJobRetryResult:
    """Run the bounded concurrent retry/failure-injection profile."""

    declared = profile or default_retry_profile()
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    try:
        application = DurableJobApplicationService(SQLiteDurableJobRepository(connection))
        created_at = _utc_second(time.time())
        for index in range(declared.jobs):
            application.submit(_submission(index, declared, created_at), actor_id="retry-submitter")
    finally:
        connection.close()

    attempts: dict[str, int] = {}
    counters: dict[str, int] = {"retry": 0, "completed": 0, "failed": 0}
    attempts_lock = threading.Lock()
    counters_lock = threading.Lock()
    retry_samples_lock = threading.Lock()
    retry_delay_samples: list[float] = []
    finished = threading.Event()
    clock_state = {"value": int(time.time())}
    clock_lock = threading.Lock()
    workers_per_tenant = declared.workers // declared.tenants
    with ThreadPoolExecutor(max_workers=declared.workers, thread_name_prefix="reconforge-retry") as pool:
        futures = [
            pool.submit(
                _worker_loop,
                f"retry-worker-{tenant:02d}-{slot:02d}",
                tenant,
                database_path,
                declared,
                attempts,
                attempts_lock,
                counters,
                counters_lock,
                finished,
                sleep_fn=sleep_fn,
                retry_delay_samples=retry_delay_samples,
                retry_samples_lock=retry_samples_lock,
                clock_state=clock_state,
                clock_lock=clock_lock,
            )
            for tenant in range(declared.tenants)
            for slot in range(workers_per_tenant)
        ]
        for future in futures:
            future.result()

    audit = connect(database_path, require_exists=True)
    try:
        digest, effects, duplicates = _effect_digest(audit)
        queued, running = audit.execute(
            "SELECT "
            "SUM(CASE WHEN status IN ('queued','retrying') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) FROM durable_jobs"
        ).fetchone()
        completed = int(audit.execute("SELECT COUNT(*) FROM durable_jobs WHERE status='completed'").fetchone()[0])
        failed = int(audit.execute("SELECT COUNT(*) FROM durable_jobs WHERE status='failed'").fetchone()[0])
        retries = int(audit.execute("SELECT COALESCE(SUM(retry_count), 0) FROM durable_jobs").fetchone()[0])
        max_retry = int(audit.execute("SELECT COALESCE(MAX(retry_count), 0) FROM durable_jobs").fetchone()[0])
    finally:
        audit.close()
    stable_delay_samples = tuple(sorted(round(value, 12) for value in retry_delay_samples))
    environment = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": int(__import__("os").cpu_count() or 1),
    }
    document: dict[str, object] = {
        "schema_version": RETRY_PROFILE_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "jobs": declared.jobs,
        "partitions_per_job": declared.partitions_per_job,
        "tenants": declared.tenants,
        "transient_failures_per_job": declared.transient_failures_per_job,
        "retry_ceiling": declared.retry_ceiling,
        "declared_partition_effects": declared.declared_partition_effects,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "scheduled_retries": retries,
        "committed_partition_effects": effects,
        "duplicate_partition_effects": duplicates,
        "final_queue_depth": int(queued or 0),
        "final_running_depth": int(running or 0),
        "max_retry_count": max_retry,
        "retry_delay_samples": stable_delay_samples,
        "effect_set_digest": digest,
        "environment": environment,
        "limitations": list(LIMITATIONS),
    }
    return DurableJobRetryResult(
        schema_version=RETRY_PROFILE_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        jobs=declared.jobs,
        partitions_per_job=declared.partitions_per_job,
        tenants=declared.tenants,
        transient_failures_per_job=declared.transient_failures_per_job,
        retry_ceiling=declared.retry_ceiling,
        declared_partition_effects=declared.declared_partition_effects,
        completed_jobs=completed,
        failed_jobs=failed,
        scheduled_retries=retries,
        committed_partition_effects=effects,
        duplicate_partition_effects=duplicates,
        final_queue_depth=int(queued or 0),
        final_running_depth=int(running or 0),
        max_retry_count=max_retry,
        effect_set_digest=digest,
        retry_delay_samples=stable_delay_samples,
        manifest_digest=_manifest_digest(document),
        environment=environment,
        limitations=LIMITATIONS,
    )


def verify_retry_manifest(result: DurableJobRetryResult, *, profile: DurableJobRetryProfile) -> None:
    """Verify structural retry, checkpoint, and no-duplicate invariants."""

    if result.schema_version != RETRY_PROFILE_SCHEMA_VERSION or result.profile_id != profile.profile_id:
        raise AssertionError("retry manifest schema or profile does not match.")
    if result.completed_jobs != profile.jobs or result.failed_jobs != 0:
        raise AssertionError("all declared jobs must complete without terminal failure.")
    expected_retries = profile.jobs * profile.transient_failures_per_job
    if result.scheduled_retries != expected_retries:
        raise AssertionError("scheduled retries do not match the injected transient-fault count.")
    if result.committed_partition_effects != profile.jobs * profile.partitions_per_job:
        raise AssertionError("partition effects do not equal the declared business effect set.")
    if result.duplicate_partition_effects != 0:
        raise AssertionError("retry resumed a partition with a duplicate business effect.")
    if result.final_queue_depth != 0 or result.final_running_depth != 0:
        raise AssertionError("retry queue or running depth did not drain.")
    if result.max_retry_count > profile.retry_ceiling:
        raise AssertionError("retry ceiling was exceeded.")
    if profile.transient_failures_per_job > 0 and not result.retry_delay_samples:
        raise AssertionError("retry delay samples are required when injected retry faults are configured.")
    if len(result.retry_delay_samples) != result.scheduled_retries:
        raise AssertionError("observed retry delay sample count does not match injected retry fault count.")
    expected_delays = Counter[float]()
    for attempt in range(profile.transient_failures_per_job):
        expected_delays[round(_retry_delay(profile, attempt), 12)] += profile.jobs
    observed_delays = Counter(result.retry_delay_samples)
    if any(expected_delay < 0 for expected_delay in result.retry_delay_samples):
        raise AssertionError("retry delay samples must be non-negative.")
    if observed_delays != Counter(expected_delays):
        raise AssertionError("retry delay coupling did not match the declared retry backoff profile.")
    if not result.effect_set_digest or not result.manifest_digest:
        raise AssertionError("retry digests are required.")
    if not result.limitations or not all("not" in limitation or "not a" in limitation for limitation in result.limitations):
        raise AssertionError("retry limitations must preserve non-claim wording.")


__all__ = [
    "DurableJobRetryProfile",
    "DurableJobRetryResult",
    "default_retry_profile",
    "run_durable_job_retry_profile",
    "verify_retry_manifest",
]
