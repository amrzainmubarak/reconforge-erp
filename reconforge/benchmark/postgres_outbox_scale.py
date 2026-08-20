"""Bounded PostgreSQL transactional-outbox multi-worker delivery profile."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any

from reconforge.infrastructure.postgres import ConnectionFactory, PostgresTenantBoundary
from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository
from reconforge.workers.outbox import OutboxWorkerSettings
from reconforge.workers.postgres_outbox import PostgresOutboxWorker

OUTBOX_SCALE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PostgresOutboxScaleProfile:
    profile_id: str
    workers: int
    events: int
    batch_size: int = 8
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        if self.workers < 1 or self.events < 1:
            raise ValueError("workers and events must be positive")
        if not 1 <= self.batch_size <= 1_000 or self.lease_seconds < 1:
            raise ValueError("batch_size or lease_seconds is outside the supported range")


@dataclass(frozen=True)
class PostgresOutboxScaleResult:
    schema_version: int
    profile_id: str
    workers: int
    events: int
    batch_size: int
    published_events: int
    duplicate_publish_attempts: int
    pending_events: int
    claimed_events: int
    dead_events: int
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


def default_profile() -> PostgresOutboxScaleProfile:
    return PostgresOutboxScaleProfile(
        profile_id="postgres-outbox-load/64-events-v1", workers=4, events=64
    )


LIMITATIONS = (
    "Synthetic one-tenant PostgreSQL 16 CI service with independent worker connections.",
    "The publisher is an injected in-process sink; no broker, external endpoint, or vendor delivery is exercised.",
    "Runtime is an observation, not throughput, capacity, SLO, queue-HA, failover, soak, or production-sizing evidence.",
    "The profile proves one-node claim/publish/acknowledge correctness only; crash-after-publish recovery and cross-host supervision remain open.",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": int(os.cpu_count() or 1),
        "database": "PostgreSQL",
    }


def _manifest_digest(document: dict[str, object]) -> str:
    stable = {key: value for key, value in document.items() if key not in {"observed_runtime_seconds", "manifest_digest", "environment"}}
    return _digest(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def run_postgres_outbox_scale_profile(
    connection_factory: ConnectionFactory,
    tenant_id: str,
    *,
    profile: PostgresOutboxScaleProfile | None = None,
    id_prefix: str = "PGOUTBOX",
) -> PostgresOutboxScaleResult:
    """Insert and concurrently publish one bounded outbox workload."""

    declared = profile or default_profile()
    normalized_prefix = str(id_prefix).strip().lower()
    event_ids = tuple(f"{normalized_prefix}-event-{index:05d}" for index in range(declared.events))
    with PostgresTenantBoundary(connection_factory).transaction(tenant_id) as connection:
        for event_id in event_ids:
            connection.execute(
                """
                INSERT INTO reconforge.outbox_events(
                    tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload
                ) VALUES(%s,%s,'scale.created','scale',%s,'{}'::jsonb)
                """,
                (tenant_id, event_id, event_id),
            )

    published: set[str] = set()
    calls = 0
    duplicate_calls = 0
    lock = threading.Lock()

    def publisher(event: Any) -> None:
        nonlocal calls, duplicate_calls
        with lock:
            calls += 1
            if event.id in published:
                duplicate_calls += 1
            published.add(event.id)

    started = time.perf_counter()

    def worker_loop(worker_index: int) -> None:
        worker = PostgresOutboxWorker(
            connection_factory,
            tenant_supplier=lambda: (tenant_id,),
            publisher=publisher,
            settings=OutboxWorkerSettings(
                worker_id=f"pg-outbox-scale-worker-{worker_index:02d}",
                poll_interval_seconds=0,
                batch_size=declared.batch_size,
                max_attempts=2,
                lease_seconds=declared.lease_seconds,
                retry_base_seconds=0,
            ),
        )
        deadline = time.perf_counter() + 120
        while True:
            with lock:
                done = len(published)
            if done >= declared.events:
                return
            if time.perf_counter() >= deadline:
                raise TimeoutError("PostgreSQL outbox scale profile did not drain before its bounded deadline")
            worker.process_once()

    with ThreadPoolExecutor(max_workers=declared.workers, thread_name_prefix="reconforge-pg-outbox") as pool:
        futures = [pool.submit(worker_loop, index) for index in range(declared.workers)]
        for future in futures:
            future.result()
    runtime = max(time.perf_counter() - started, 0.0)

    with PostgresTenantBoundary(connection_factory).transaction(tenant_id) as connection:
        summary = PostgresOutboxRepository(connection).summary(tenant_id=tenant_id)

    normalized_ids = [event_id.rsplit("-", 1)[-1] for event_id in sorted(published)]
    effect_digest = _digest(json.dumps(normalized_ids, separators=(",", ":"), ensure_ascii=True))
    document: dict[str, object] = {
        "schema_version": OUTBOX_SCALE_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "events": declared.events,
        "batch_size": declared.batch_size,
        "published_events": len(published),
        "duplicate_publish_attempts": duplicate_calls,
        "pending_events": int(summary["pending"]),
        "claimed_events": int(summary["claimed"]),
        "dead_events": int(summary["dead"]),
        "effect_set_digest": effect_digest,
        "limitations": list(LIMITATIONS),
    }
    return PostgresOutboxScaleResult(
        schema_version=OUTBOX_SCALE_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        events=declared.events,
        batch_size=declared.batch_size,
        published_events=len(published),
        duplicate_publish_attempts=duplicate_calls,
        pending_events=int(summary["pending"]),
        claimed_events=int(summary["claimed"]),
        dead_events=int(summary["dead"]),
        effect_set_digest=effect_digest,
        observed_runtime_seconds=round(runtime, 4),
        environment=_environment(),
        manifest_digest=_manifest_digest(document),
        limitations=LIMITATIONS,
    )


def verify_postgres_outbox_scale_result(
    result: PostgresOutboxScaleResult,
    *,
    profile: PostgresOutboxScaleProfile | None = None,
) -> None:
    declared = profile or default_profile()
    if result.schema_version != OUTBOX_SCALE_SCHEMA_VERSION or result.profile_id != declared.profile_id:
        raise AssertionError("PostgreSQL outbox scale profile mismatch")
    if result.published_events != declared.events or result.duplicate_publish_attempts != 0:
        raise AssertionError("PostgreSQL outbox delivery was incomplete or duplicated")
    if result.pending_events != 0 or result.claimed_events != 0 or result.dead_events != 0:
        raise AssertionError("PostgreSQL outbox queue did not drain cleanly")
    if not result.effect_set_digest or not result.manifest_digest:
        raise AssertionError("PostgreSQL outbox scale result is missing digests")


__all__ = [
    "LIMITATIONS",
    "OUTBOX_SCALE_SCHEMA_VERSION",
    "PostgresOutboxScaleProfile",
    "PostgresOutboxScaleResult",
    "default_profile",
    "run_postgres_outbox_scale_profile",
    "verify_postgres_outbox_scale_result",
]
