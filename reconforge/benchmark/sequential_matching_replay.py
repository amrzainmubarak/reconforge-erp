"""Crash/resume and adapter-parity profile for sequential matching.

The profile executes bounded carry-forward, contiguous sequence-window, and
reversal-pairing partitions through the public strategy adapters.  Each
partition is persisted as a durable-job effect; an injected retry must resume
from the last checkpoint without changing the effect digest.  The profile is
synthetic correctness evidence, not a PostgreSQL capacity or production claim.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission, LeasedJob
from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobOutputManifest
from reconforge.infrastructure.carry_forward_strategy import CarryForwardFifoStrategy
from reconforge.infrastructure.reversal_matching_strategy import ReversalPairingStrategy
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository
from reconforge.workers.postgres_reconciliation import ReconciliationExecutionContext, ReconciliationInputPartition
from reconforge.workers.postgres_sequential_matching import PostgresSequentialMatchingAdapter

REPLAY_SCHEMA_VERSION = 1
REPLAY_PROFILE_ID = "sequential-matching-replay/synthetic-v1"
_TENANT = "TENANT-SEQUENTIAL-REPLAY"
_WORKSPACE = f"{_TENANT}/workspace"
_ENTITY = f"{_TENANT}/entity"
_JOB_ID = "SEQUENTIAL-REPLAY-1"


@dataclass(frozen=True)
class SequentialMatchingReplayProfile:
    """Declared bounded replay profile."""

    profile_id: str = REPLAY_PROFILE_ID
    fault_after_partition: int = 1
    retry_ceiling: int = 1

    def __post_init__(self) -> None:
        if not self.profile_id or self.fault_after_partition < 1 or self.retry_ceiling < 1:
            raise ValueError("profile and fault/retry bounds must be positive.")
        if self.fault_after_partition >= len(_partition_requests()):
            raise ValueError("fault_after_partition must leave at least one partition to resume.")


@dataclass(frozen=True)
class SequentialMatchingReplayResult:
    schema_version: int
    profile_id: str
    partition_count: int
    fault_after_partition: int
    retry_count: int
    completed_units: int
    duplicate_effects: int
    persisted_effect_digest: str
    expected_effect_digest: str
    adapter_parity: bool
    mutation_guard_passed: bool
    queue_depth: int
    running_depth: int
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "partition_count": self.partition_count,
            "fault_after_partition": self.fault_after_partition,
            "retry_count": self.retry_count,
            "completed_units": self.completed_units,
            "duplicate_effects": self.duplicate_effects,
            "persisted_effect_digest": self.persisted_effect_digest,
            "expected_effect_digest": self.expected_effect_digest,
            "adapter_parity": self.adapter_parity,
            "mutation_guard_passed": self.mutation_guard_passed,
            "queue_depth": self.queue_depth,
            "running_depth": self.running_depth,
            "limitations": list(self.limitations),
        }


LIMITATIONS = (
    "Synthetic SQLite durable-job replay only; a live PostgreSQL database is not exercised by this profile.",
    "Adapter parity compares the public strategy result with the PostgreSQL-worker projection contract; it is not engine throughput or deployment evidence.",
    "The three partitions are bounded correctness fixtures and are not a 10K/100K/1M performance claim.",
    "The mutation guard is an adversarial regression sentinel; no source-code mutation-testing score is claimed.",
)


def _partition_requests() -> tuple[MatchingStrategyRequest, ...]:
    common = {"currency": "USD", "date": "2026-08-01", "partition": "SEQUENTIAL"}
    return (
        MatchingStrategyRequest(
            left_records=(
                {**common, "id": "O1", "amount": "100"},
                {**common, "id": "O2", "amount": "50", "date": "2026-08-02"},
            ),
            right_records=({**common, "id": "S1", "amount": "100", "date": "2026-08-03"},),
            amount_tolerance="0",
            date_window_days=10,
            mode="carry-forward",
        ),
        MatchingStrategyRequest(
            left_records=(
                {**common, "id": "O3", "amount": "40"},
                {**common, "id": "O4", "amount": "60", "date": "2026-08-02"},
            ),
            right_records=({**common, "id": "S2", "amount": "100", "date": "2026-08-03"},),
            amount_tolerance="0",
            date_window_days=10,
            mode="sequence-window",
        ),
        MatchingStrategyRequest(
            left_records=({**common, "id": "J1", "amount": "100"},),
            right_records=(
                {
                    **common,
                    "id": "R1",
                    "amount": "-100",
                    "date": "2026-08-02",
                    "reversal_of": "J1",
                },
            ),
            amount_tolerance="0",
            date_window_days=10,
            mode="reversal-pairing",
        ),
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def _request_payload(request: MatchingStrategyRequest) -> dict[str, object]:
    return {
        "left": [dict(record) for record in request.left_records],
        "right": [dict(record) for record in request.right_records],
        "mode": request.mode,
        "amount_tolerance": request.amount_tolerance,
        "date_window_days": request.date_window_days,
    }


def _submission(profile: SequentialMatchingReplayProfile, created_at: str) -> JobSubmission:
    return JobSubmission(
        job_id=_JOB_ID,
        idempotency_scope=f"{_TENANT}/sequential",
        idempotency_key=profile.profile_id,
        tenant_id=_TENANT,
        workspace_id=_WORKSPACE,
        entity_id=_ENTITY,
        input_digest=_digest([_request_payload(item) for item in _partition_requests()]),
        config_digest=_digest({"profile": profile.profile_id}),
        worker_version="sequential-matching-replay/1.0.0",
        total_units=len(_partition_requests()),
        retry_ceiling=profile.retry_ceiling,
        created_at=created_at,
    )


def _record(value: dict[str, object]) -> dict[str, object]:
    amount = Decimal(str(value["amount"]))
    record = {
        "source_id": str(value["id"]),
        "amount_decimal": amount,
        "date_value": date.fromisoformat(str(value["date"])),
        "currency_code": str(value["currency"]),
        "attributes_json": dict(value),
    }
    return record


def _adapter_digest(request: MatchingStrategyRequest) -> str:
    context = ReconciliationExecutionContext(
        run={
            "rule_json": {
                "matching_mode": request.mode,
                "amount_tolerance": request.amount_tolerance,
                "date_window_days": request.date_window_days,
            }
        },
        left_inputs=tuple(_record(dict(item)) for item in request.left_records),
        right_inputs=tuple(_record(dict(item)) for item in request.right_records),
        heartbeat=lambda completed: {"completed": completed},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (
            ReconciliationInputPartition(
                partition_key=str(request.left_records[0].get(request.partition_field, "")),
                left_inputs=tuple(_record(dict(item)) for item in request.left_records),
                right_inputs=tuple(_record(dict(item)) for item in request.right_records),
            ),
        ),
    )
    projected = PostgresSequentialMatchingAdapter()(context)
    lineage_digests: set[str] = set()
    for row in projected.results:
        lineage = row.get("lineage")
        if isinstance(lineage, dict):
            lineage_digests.add(str(lineage.get("strategy_result_digest", "")))
    if len(lineage_digests) != 1:
        raise AssertionError("sequential adapter must expose exactly one result digest")
    return next(iter(lineage_digests))


def _execute_partition(request: MatchingStrategyRequest) -> tuple[str, bool]:
    strategy: CarryForwardFifoStrategy | ReversalPairingStrategy
    strategy = ReversalPairingStrategy() if request.mode == "reversal-pairing" else CarryForwardFifoStrategy()
    direct = strategy.execute(request)
    return direct.decision_digest, direct.decision_digest == _adapter_digest(request)


def _mutated_request(request: MatchingStrategyRequest) -> MatchingStrategyRequest:
    first = dict(request.left_records[0])
    first["amount"] = str((Decimal(str(first["amount"])) + Decimal("0.01")).quantize(Decimal("0.01")))
    return MatchingStrategyRequest(
        left_records=(first,) + request.left_records[1:],
        right_records=request.right_records,
        amount_tolerance=request.amount_tolerance,
        date_window_days=request.date_window_days,
        mode=request.mode,
    )


def _run_once(
    database_path: Path,
    profile: SequentialMatchingReplayProfile,
    *,
    inject_fault: bool,
) -> tuple[str, int, int, bool, bool]:
    run_migrations(database_path)
    base_epoch = int(time.time())
    connection = connect(database_path, require_exists=True)
    try:
        DurableJobApplicationService(SQLiteDurableJobRepository(connection)).submit(
            _submission(profile, _timestamp(base_epoch)), actor_id="sequential-replay-submitter"
        )
    finally:
        connection.close()

    connection = connect(database_path, require_exists=True)
    worker = DurableJobWorkerService(SQLiteDurableJobRepository(connection))
    clock = base_epoch
    clock_lock = Lock()

    def now() -> str:
        nonlocal clock
        with clock_lock:
            clock += 1
            return _timestamp(clock)

    try:
        attempts = 0
        adapter_parity = True
        mutation_guard = True
        leased: LeasedJob | None = None
        while True:
            leased = worker.claim(
                tenant_id=_TENANT,
                worker_id=f"sequential-replay-worker-{attempts}",
                occurred_at=now(),
                lease_expires_at=_timestamp(clock + 60),
            )
            if leased is None:
                raise AssertionError("sequential replay job could not be claimed")
            attempts += 1
            completed = {effect.ordinal for effect in worker.completed_effects(leased)}
            for ordinal, request in enumerate(_partition_requests(), start=1):
                if ordinal in completed:
                    continue
                output_digest, equal = _execute_partition(request)
                adapter_parity = adapter_parity and equal
                if ordinal == 1:
                    mutation_guard = output_digest != _execute_partition(_mutated_request(request))[0]
                kwargs: dict[str, Any] = {
                    "leased_job": leased,
                    "partition_key": f"partition/{ordinal:04d}",
                    "ordinal": ordinal,
                    "input_digest": _digest(_request_payload(request)),
                    "output_digest": output_digest,
                    "effect_reference": f"effect/{_JOB_ID}/{ordinal:04d}",
                    "occurred_at": now(),
                }
                if ordinal == len(_partition_requests()):
                    worker.complete_partition(
                        **kwargs,
                        output_manifest=JobOutputManifest(
                            schema_version=1,
                            digest=_digest(f"{_JOB_ID}:manifest"),
                            reference=f"manifest/{_JOB_ID}/v1",
                        ),
                    )
                else:
                    leased = worker.commit_partition(**kwargs, completed_units=ordinal)
                if inject_fault and attempts == 1 and ordinal == profile.fault_after_partition:
                    worker.schedule_retry(leased, occurred_at=now())
                    break
            if inject_fault and attempts == 1:
                continue
            break
        if leased is None:
            raise AssertionError("sequential replay worker did not retain a lease")
        effects = worker.completed_effects(leased)
        payload = [(effect.partition_key, effect.ordinal, effect.input_digest, effect.output_digest) for effect in effects]
        return _digest(payload), len(effects), attempts - 1, adapter_parity, mutation_guard
    finally:
        connection.close()


def run_sequential_matching_replay_fault_matrix(
    directory: Path,
    *,
    profile: SequentialMatchingReplayProfile | None = None,
) -> tuple[SequentialMatchingReplayResult, ...]:
    """Run recovery after every non-terminal sequential partition."""

    declared = profile or SequentialMatchingReplayProfile()
    results: list[SequentialMatchingReplayResult] = []
    for fault_point in range(1, len(_partition_requests())):
        point = SequentialMatchingReplayProfile(
            profile_id=f"{declared.profile_id}/fault-{fault_point}",
            fault_after_partition=fault_point,
            retry_ceiling=declared.retry_ceiling,
        )
        result = run_sequential_matching_replay_profile(directory / f"fault-{fault_point}.db", profile=point)
        verify_sequential_matching_replay(result)
        results.append(result)
    return tuple(results)


def run_sequential_matching_replay_profile(
    database_path: Path,
    *,
    profile: SequentialMatchingReplayProfile | None = None,
) -> SequentialMatchingReplayResult:
    """Run an uninterrupted baseline and a one-fault crash/resume replay."""

    declared = profile or SequentialMatchingReplayProfile()
    expected_digest, expected_units, _baseline_retry, baseline_parity, baseline_mutation = _run_once(
        database_path.with_name(database_path.stem + "-baseline.db"), declared, inject_fault=False
    )
    persisted_digest, units, retries, replay_parity, replay_mutation = _run_once(
        database_path, declared, inject_fault=True
    )
    connection = connect(database_path, require_exists=True)
    try:
        queue, running = connection.execute(
            "SELECT SUM(status IN ('queued','retrying')), SUM(status='running') FROM durable_jobs"
        ).fetchone()
        duplicate = int(
            connection.execute(
                "SELECT COUNT(*) - COUNT(DISTINCT job_id || ':' || partition_key) FROM durable_job_partition_effects"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return SequentialMatchingReplayResult(
        schema_version=REPLAY_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        partition_count=len(_partition_requests()),
        fault_after_partition=declared.fault_after_partition,
        retry_count=retries,
        completed_units=units,
        duplicate_effects=duplicate,
        persisted_effect_digest=persisted_digest,
        expected_effect_digest=expected_digest,
        adapter_parity=baseline_parity and replay_parity,
        mutation_guard_passed=baseline_mutation and replay_mutation,
        queue_depth=int(queue or 0),
        running_depth=int(running or 0),
        limitations=LIMITATIONS,
    )


def verify_sequential_matching_replay(result: SequentialMatchingReplayResult) -> None:
    """Verify replay, adapter parity, and adversarial mutation invariants."""

    if result.schema_version != REPLAY_SCHEMA_VERSION:
        raise AssertionError("unsupported replay schema")
    if result.persisted_effect_digest != result.expected_effect_digest:
        raise AssertionError("crash/resume digest differs from uninterrupted replay")
    if result.completed_units != result.partition_count or result.retry_count != 1:
        raise AssertionError("replay did not complete exactly one bounded retry")
    if result.duplicate_effects != 0 or result.queue_depth != 0 or result.running_depth != 0:
        raise AssertionError("replay left duplicate effects or non-terminal job state")
    if not result.adapter_parity or not result.mutation_guard_passed:
        raise AssertionError("adapter parity or adversarial mutation guard failed")


__all__ = [
    "SequentialMatchingReplayProfile",
    "SequentialMatchingReplayResult",
    "run_sequential_matching_replay_fault_matrix",
    "run_sequential_matching_replay_profile",
    "verify_sequential_matching_replay",
]
