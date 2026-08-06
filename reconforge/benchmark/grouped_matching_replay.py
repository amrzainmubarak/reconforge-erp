"""Crash/resume and cross-engine replay profile for grouped matching.

The profile runs a bounded synthetic portfolio through the public strategy
adapter and the pure application boundary, then persists each partition as a
durable-job effect. A fault can be injected after a committed partition; the
retry owner resumes from the checkpoint and must reproduce the uninterrupted
effect digest. This is a correctness/replay profile, not a capacity claim.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock

from reconforge.application.grouped_matching import GroupedMatchingApplicationService, GroupedMatchRequest
from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission, LeasedJob
from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.db import connect, run_migrations
from reconforge.domain.grouped_matching import GroupedMatchPolicy
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository

REPLAY_SCHEMA_VERSION = 1
REPLAY_PROFILE_ID = "grouped-matching-replay/synthetic-v1"


@dataclass(frozen=True)
class GroupedMatchingReplayProfile:
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
class GroupedMatchingReplayResult:
    schema_version: int
    profile_id: str
    partition_count: int
    fault_after_partition: int
    retry_count: int
    completed_units: int
    duplicate_effects: int
    persisted_effect_digest: str
    expected_effect_digest: str
    cross_engine_equal: bool
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
            "cross_engine_equal": self.cross_engine_equal,
            "mutation_guard_passed": self.mutation_guard_passed,
            "queue_depth": self.queue_depth,
            "running_depth": self.running_depth,
            "limitations": list(self.limitations),
        }


def run_grouped_matching_replay_fault_matrix(
    directory: Path,
    *,
    profile: GroupedMatchingReplayProfile | None = None,
) -> tuple[GroupedMatchingReplayResult, ...]:
    """Exercise crash/resume after every non-terminal partition checkpoint.

    Each fault point runs against a fresh SQLite database.  The matrix keeps
    the existing bounded profile and public replay verifier, while making the
    recovery contract explicit for every resumable checkpoint rather than only
    the first partition.
    """

    declared = profile or GroupedMatchingReplayProfile()
    partition_count = len(_partition_requests())
    fault_points = tuple(range(1, partition_count))
    results: list[GroupedMatchingReplayResult] = []
    for fault_point in fault_points:
        point_profile = GroupedMatchingReplayProfile(
            profile_id=f"{declared.profile_id}/fault-{fault_point}",
            fault_after_partition=fault_point,
            retry_ceiling=declared.retry_ceiling,
        )
        result = run_grouped_matching_replay_profile(
            directory / f"fault-{fault_point}.db", profile=point_profile
        )
        verify_grouped_matching_replay(result)
        results.append(result)
    return tuple(results)


LIMITATIONS = (
    "Synthetic SQLite replay only; PostgreSQL matcher parity is not exercised by this profile.",
    "The portfolio is bounded to four partitions and is not a 10K/100K/1M performance claim.",
    "Mutation guard is an adversarial regression sentinel; no mutation-testing tool score is claimed.",
)


def _partition_requests() -> tuple[MatchingStrategyRequest, ...]:
    common = {"currency": "USD", "date": "2026-08-01", "partition": "AR"}
    return (
        MatchingStrategyRequest(
            left_records=(
                {**common, "id": "L1", "amount": "100"},
            ),
            right_records=(
                {**common, "id": "R1", "amount": "40"},
                {**common, "id": "R2", "amount": "60"},
            ),
            mode="one-to-many",
        ),
        MatchingStrategyRequest(
            left_records=(
                {**common, "id": "L2", "amount": "30"},
                {**common, "id": "L3", "amount": "70"},
            ),
            right_records=(
                {**common, "id": "R3", "amount": "100"},
            ),
            mode="many-to-one",
        ),
        MatchingStrategyRequest(
            left_records=(
                {**common, "id": "L4", "amount": "30"},
                {**common, "id": "L5", "amount": "70"},
            ),
            right_records=(
                {**common, "id": "R4", "amount": "25"},
                {**common, "id": "R5", "amount": "75"},
            ),
            mode="many-to-many",
        ),
        MatchingStrategyRequest(
            left_records=({**common, "id": "L6", "amount": "100"},),
            right_records=({**common, "id": "R6", "amount": "75"},),
            mode="portfolio",
            allow_partial_settlement=True,
        ),
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def _submission(profile: GroupedMatchingReplayProfile, created_at: str) -> JobSubmission:
    return JobSubmission(
        job_id="GROUPED-REPLAY-1",
        idempotency_scope="TENANT-REPLAY/grouped",
        idempotency_key=profile.profile_id,
        tenant_id="TENANT-REPLAY",
        workspace_id="TENANT-REPLAY/workspace",
        entity_id="TENANT-REPLAY/entity",
        input_digest=_digest([_request_payload(item) for item in _partition_requests()]),
        config_digest=_digest({"profile": profile.profile_id}),
        worker_version="grouped-matching-replay/1.0.0",
        total_units=len(_partition_requests()),
        retry_ceiling=profile.retry_ceiling,
        created_at=created_at,
    )


def _request_payload(request: MatchingStrategyRequest) -> dict[str, object]:
    return {
        "left": [dict(record) for record in request.left_records],
        "right": [dict(record) for record in request.right_records],
        "mode": request.mode,
        "amount_tolerance": request.amount_tolerance,
        "allow_partial_settlement": request.allow_partial_settlement,
    }


def _execute_partition(request: MatchingStrategyRequest) -> tuple[str, bool]:
    """Return one cross-engine output digest and whether both paths agree."""

    strategy_result = GroupedSubsetSumStrategy().execute(request)
    application_request = GroupedMatchRequest(
        left_records=request.left_records,
        right_records=request.right_records,
        policy=GroupedMatchPolicy(
            mode=request.mode,  # type: ignore[arg-type]
            amount_tolerance=Decimal(request.amount_tolerance),
            date_window_days=request.date_window_days,
            max_left_cardinality=4,
            max_right_cardinality=4,
            max_search_evaluations=25_000,
            portfolio_allow_partial_settlement=request.allow_partial_settlement,
        ),
    )
    service = GroupedMatchingApplicationService()
    if request.mode == "portfolio":
        direct_results = service.execute_portfolio(application_request).decisions
    else:
        direct_results = (service.execute(application_request),)
    direct_digests = tuple(decision.decision_digest for decision in direct_results)
    adapter_digests = tuple(str(item["decision_digest"]) for item in strategy_result.results)
    equal = direct_digests == adapter_digests
    return _digest({"strategy": strategy_result.decision_digest, "decisions": direct_digests}), equal


def _mutated_request(request: MatchingStrategyRequest) -> MatchingStrategyRequest:
    """Create a deterministic one-cent mutation used by the adversarial guard."""

    first = dict(request.left_records[0])
    first["amount"] = str((Decimal(str(first["amount"])) + Decimal("0.01")).quantize(Decimal("0.01")))
    return MatchingStrategyRequest(
        left_records=(first,) + request.left_records[1:],
        right_records=request.right_records,
        mode=request.mode,
        allow_partial_settlement=request.allow_partial_settlement,
    )


def _run_once(database_path: Path, profile: GroupedMatchingReplayProfile, *, inject_fault: bool) -> tuple[str, int, int, bool, bool]:
    run_migrations(database_path)
    base_epoch = int(time.time())
    connection = connect(database_path, require_exists=True)
    try:
        application = DurableJobApplicationService(SQLiteDurableJobRepository(connection))
        application.submit(_submission(profile, _timestamp(base_epoch)), actor_id="replay-submitter")
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
        cross_engine_equal = True
        mutated_digest_changed = True
        leased: LeasedJob | None = None
        while True:
            leased = worker.claim(
                tenant_id="TENANT-REPLAY",
                worker_id=f"replay-worker-{attempts}",
                occurred_at=now(),
                lease_expires_at=_timestamp(clock + 60),
            )
            if leased is None:
                raise AssertionError("replay job could not be claimed")
            attempts += 1
            completed = {effect.ordinal for effect in worker.completed_effects(leased)}
            for ordinal, request in enumerate(_partition_requests(), start=1):
                if ordinal in completed:
                    continue
                output_digest, equal = _execute_partition(request)
                cross_engine_equal = cross_engine_equal and equal
                if ordinal == 1:
                    mutated_digest_changed = output_digest != _execute_partition(_mutated_request(request))[0]
                if ordinal == len(_partition_requests()):
                    worker.complete_partition(
                        leased,
                        partition_key=f"partition/{ordinal:04d}",
                        ordinal=ordinal,
                        input_digest=_digest(_request_payload(request)),
                        output_digest=output_digest,
                        effect_reference=f"effect/GROUPED-REPLAY-1/{ordinal:04d}",
                        occurred_at=now(),
                        output_manifest=__import__("reconforge.domain.jobs", fromlist=["JobOutputManifest"]).JobOutputManifest(
                            schema_version=1,
                            digest=_digest("GROUPED-REPLAY-1:manifest"),
                            reference="manifest/GROUPED-REPLAY-1/v1",
                        ),
                    )
                else:
                    leased = worker.commit_partition(
                        leased,
                        partition_key=f"partition/{ordinal:04d}",
                        ordinal=ordinal,
                        completed_units=ordinal,
                        input_digest=_digest(_request_payload(request)),
                        output_digest=output_digest,
                        effect_reference=f"effect/GROUPED-REPLAY-1/{ordinal:04d}",
                        occurred_at=now(),
                    )
                if inject_fault and attempts == 1 and ordinal == profile.fault_after_partition:
                    worker.schedule_retry(leased, occurred_at=now())
                    break
            if inject_fault and attempts == 1:
                continue
            break
        effects = worker.completed_effects(leased)
        payload = [(effect.partition_key, effect.ordinal, effect.input_digest, effect.output_digest) for effect in effects]
        return _digest(payload), len(effects), attempts - 1, cross_engine_equal, mutated_digest_changed
    finally:
        connection.close()


def run_grouped_matching_replay_profile(
    database_path: Path, *, profile: GroupedMatchingReplayProfile | None = None
) -> GroupedMatchingReplayResult:
    """Run the uninterrupted baseline and the injected crash/resume replay."""

    declared = profile or GroupedMatchingReplayProfile()
    expected_digest, expected_units, _retries, baseline_equal, baseline_mutation = _run_once(
        database_path.with_name(database_path.stem + "-baseline.db"), declared, inject_fault=False
    )
    persisted_digest, units, retries, cross_equal, mutation_guard = _run_once(database_path, declared, inject_fault=True)
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
    return GroupedMatchingReplayResult(
        schema_version=REPLAY_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        partition_count=len(_partition_requests()),
        fault_after_partition=declared.fault_after_partition,
        retry_count=retries,
        completed_units=units,
        duplicate_effects=duplicate,
        persisted_effect_digest=persisted_digest,
        expected_effect_digest=expected_digest,
        cross_engine_equal=baseline_equal and cross_equal,
        mutation_guard_passed=baseline_mutation and mutation_guard,
        queue_depth=int(queue or 0),
        running_depth=int(running or 0),
        limitations=LIMITATIONS,
    )


def verify_grouped_matching_replay(result: GroupedMatchingReplayResult) -> None:
    """Verify replay, parity, and adversarial mutation invariants."""

    if result.schema_version != REPLAY_SCHEMA_VERSION:
        raise AssertionError("unsupported replay schema")
    if result.persisted_effect_digest != result.expected_effect_digest:
        raise AssertionError("crash/resume digest differs from uninterrupted replay")
    if result.completed_units != result.partition_count or result.retry_count != 1:
        raise AssertionError("replay did not complete exactly one bounded retry")
    if result.duplicate_effects != 0 or result.queue_depth != 0 or result.running_depth != 0:
        raise AssertionError("replay left duplicate effects or non-terminal job state")
    if not result.cross_engine_equal or not result.mutation_guard_passed:
        raise AssertionError("cross-engine or adversarial mutation guard failed")


__all__ = [
    "GroupedMatchingReplayProfile",
    "GroupedMatchingReplayResult",
    "run_grouped_matching_replay_fault_matrix",
    "run_grouped_matching_replay_profile",
    "verify_grouped_matching_replay",
]
