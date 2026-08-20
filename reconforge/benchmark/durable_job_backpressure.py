"""Bounded producer/backpressure profile over the existing durable-job worker."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from reconforge.application.jobs import DurableJobApplicationService
from reconforge.benchmark.durable_job_load import (
    DurableJobLoadProfile,
    _effect_set_digest,
    _job_id,
    _job_submission,
    _tenant_id,
    _utc_second,
    _worker_loop,
)
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository

BACKPRESSURE_PROFILE_ID = "durable-job-load/backpressure-tier-v1"


@dataclass(frozen=True)
class DurableJobBackpressureResult:
    profile_id: str
    jobs: int
    workers: int
    tenants: int
    max_queued_jobs: int
    observed_max_queue_depth: int
    completed_jobs: int
    committed_partition_effects: int
    duplicate_partition_effects: int
    final_queue_depth: int
    final_running_depth: int
    effect_set_digest: str
    manifest_digest: str
    observed_runtime_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "jobs": self.jobs,
            "workers": self.workers,
            "tenants": self.tenants,
            "max_queued_jobs": self.max_queued_jobs,
            "observed_max_queue_depth": self.observed_max_queue_depth,
            "completed_jobs": self.completed_jobs,
            "committed_partition_effects": self.committed_partition_effects,
            "duplicate_partition_effects": self.duplicate_partition_effects,
            "final_queue_depth": self.final_queue_depth,
            "final_running_depth": self.final_running_depth,
            "effect_set_digest": self.effect_set_digest,
            "manifest_digest": self.manifest_digest,
            "observed_runtime_seconds": self.observed_runtime_seconds,
            "limitations": [
                "Single shared SQLite database; this is a producer queue-cap observation, not distributed backpressure.",
                "Runtime is hardware-dependent and is not an SLO or capacity claim.",
                "PostgreSQL queue parity, retry backoff, soak, cancellation-under-load, and HA/DR remain unverified.",
            ],
        }


def _queue_depth(connection: object) -> int:
    row = connection.execute("SELECT COUNT(*) FROM durable_jobs WHERE status IN ('queued','retrying')").fetchone()  # type: ignore[attr-defined]
    return int(row[0])


def run_backpressure_profile(
    database_path: Path,
    *,
    jobs: int = 64,
    workers: int = 8,
    partitions_per_job: int = 4,
    tenants: int = 4,
    max_queued_jobs: int = 8,
) -> DurableJobBackpressureResult:
    if jobs < 1 or workers < 1 or partitions_per_job < 1 or tenants < 1:
        raise ValueError("backpressure profile dimensions must be positive")
    if workers % tenants or tenants > jobs or not 1 <= max_queued_jobs <= jobs:
        raise ValueError("workers must divide tenants and queue cap must fit the declared jobs")
    profile = DurableJobLoadProfile(
        profile_id=BACKPRESSURE_PROFILE_ID,
        workers=workers,
        jobs=jobs,
        partitions_per_job=partitions_per_job,
        tenants=tenants,
        lease_seconds=60,
    )
    run_migrations(database_path)
    started = time.time()
    counters: dict[str, int] = {_tenant_id(index): 0 for index in range(tenants)}
    state_lock = threading.Lock()
    finish_event = threading.Event()
    observed_max = [0]
    producer_done = threading.Event()

    def produce() -> None:
        connection = connect(database_path, require_exists=True)
        try:
            application = DurableJobApplicationService(SQLiteDurableJobRepository(connection))
            created_at = _utc_second(started)
            for index in range(jobs):
                while _queue_depth(connection) >= max_queued_jobs:
                    observed_max[0] = max(observed_max[0], _queue_depth(connection))
                    time.sleep(0.002)
                observed_max[0] = max(observed_max[0], _queue_depth(connection))
                tenant = _tenant_id(index % tenants)
                job_id = _job_id(index)
                application.submit(
                    _job_submission(job_id, f"bp-key-{index:06d}", tenant, partitions_per_job, created_at),
                    actor_id="backpressure-producer",
                )
                observed_max[0] = max(observed_max[0], _queue_depth(connection))
        finally:
            connection.close()
            producer_done.set()

    def observe_done() -> bool:
        return producer_done.is_set() and sum(counters.values()) >= jobs

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reconforge-backpressure") as pool:
        futures = [
            pool.submit(
                _worker_loop,
                worker_id=f"bp-worker-{tenant:02d}-{slot:02d}",
                tenant_index=tenant,
                database_path=database_path,
                profile=profile,
                counters=counters,
                state_lock=state_lock,
                finish_event=finish_event,
            )
            for tenant in range(tenants)
            for slot in range(workers // tenants)
        ]
        producer = threading.Thread(target=produce, name="reconforge-backpressure-producer")
        producer.start()
        while not observe_done():
            time.sleep(0.005)
        finish_event.set()
        producer.join()
        for future in futures:
            future.result()

    runtime = round(time.time() - started, 4)
    connection = connect(database_path, require_exists=True)
    try:
        queue = int(connection.execute("SELECT COUNT(*) FROM durable_jobs WHERE status IN ('queued','retrying')").fetchone()[0])
        running = int(connection.execute("SELECT COUNT(*) FROM durable_jobs WHERE status='running'").fetchone()[0])
        duplicate = int(
            connection.execute(
                "SELECT COALESCE(SUM(occurrences - 1), 0) FROM (SELECT COUNT(*) AS occurrences FROM durable_job_partition_effects GROUP BY job_id, partition_key HAVING COUNT(*) > 1)"
            ).fetchone()[0]
        )
        digest, effects, _ = _effect_set_digest(connection, profile)
    finally:
        connection.close()
    document = {
        "profile_id": BACKPRESSURE_PROFILE_ID,
        "jobs": jobs,
        "workers": workers,
        "tenants": tenants,
        "partitions_per_job": partitions_per_job,
        "max_queued_jobs": max_queued_jobs,
        "observed_max_queue_depth": observed_max[0],
        "completed_jobs": sum(counters.values()),
        "committed_partition_effects": effects,
        "duplicate_partition_effects": duplicate,
        "final_queue_depth": queue,
        "final_running_depth": running,
        "effect_set_digest": digest,
    }
    manifest_digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return DurableJobBackpressureResult(
        profile_id=BACKPRESSURE_PROFILE_ID,
        jobs=jobs,
        workers=workers,
        tenants=tenants,
        max_queued_jobs=max_queued_jobs,
        observed_max_queue_depth=observed_max[0],
        completed_jobs=sum(counters.values()),
        committed_partition_effects=effects,
        duplicate_partition_effects=duplicate,
        final_queue_depth=queue,
        final_running_depth=running,
        effect_set_digest=digest,
        manifest_digest=manifest_digest,
        observed_runtime_seconds=runtime,
    )


def verify_backpressure_result(result: DurableJobBackpressureResult) -> None:
    if result.completed_jobs != result.jobs:
        raise AssertionError("backpressure profile did not complete every job")
    if result.observed_max_queue_depth > result.max_queued_jobs:
        raise AssertionError("producer exceeded the queue cap")
    if result.duplicate_partition_effects != 0:
        raise AssertionError("backpressure profile duplicated a partition effect")
    if result.final_queue_depth != 0 or result.final_running_depth != 0:
        raise AssertionError("backpressure profile left queued or running jobs")
    if not result.effect_set_digest or not result.manifest_digest:
        raise AssertionError("backpressure profile digests are required")
