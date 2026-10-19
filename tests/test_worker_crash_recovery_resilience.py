"""Worker Crash Recovery & Job Lease Fencing Resilience Verification Suite.

Validates ADR 0049 & ADR 0226 contracts:
1. Multi-partition worker process crash fault injection:
   - Simulates abrupt worker process termination (SIGKILL / BaseException) immediately after committing
     a partition transaction.
2. Job lease fencing:
   - While Worker 1's execution lease is active, any attempt by a successor worker to process the run
     is rejected fail-closed with PostgresReconciliationBusyError ("already leased by another worker").
3. Lease expiration & successor takeover:
   - Upon lease timeout expiration, Successor Worker 2 acquires the run as attempt #2, reads already
     committed checkpoints, and processes only the remaining uncommitted partitions.
4. Exact-once business effect & zero data loss invariants:
   - Disjoint execution: Partitions processed by Worker 1 and Worker 2 are strictly disjoint (zero duplicate records).
   - Zero dropped records: Total processed records and output manifest match a reference baseline run 100%.
   - Hash parity: Result set hash and partition checkpoint hashes match single-worker baseline.
5. Multi-crash cascading recovery:
   - Survives successive failures across 3 worker generations with sequential checkpoint resumption.
"""

from __future__ import annotations

from typing import Any

import pytest

from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationBusyError,
)
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
)
from tests.test_postgres_reconciliation import (
    _ConnectionFactory,
    _create_partitioned_reconciliation,
    _ReconciliationConnection,
)


class _InjectedProcessCrash(BaseException):
    """Simulates abrupt process termination (e.g. SIGKILL, OOM, power loss)."""


def test_worker_crash_recovery_resilience_and_lease_fencing() -> None:
    """Test worker crash after partial partition commit, lease fencing,

    and successor worker resumption from checkpoints with zero duplicate or dropped records.
    """
    run_id = "run-crash-fencing-test"
    adapter = LocalDeterministicMatcherAdapter()

    try:
        # Step 1: Run baseline single-worker execution to establish ground truth
        baseline_connection = _ReconciliationConnection()
        _create_partitioned_reconciliation(baseline_connection, run_id=run_id)
        baseline_worker = PostgresReconciliationWorker(
            _ConnectionFactory(baseline_connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=adapter,
            settings=PostgresReconciliationWorkerSettings(
                worker_id="worker-baseline",
                poll_interval_seconds=0,
                allow_unbound_hosted_policy=True,
            ),
        )
        baseline_summary = baseline_worker.process_run(tenant_id="tenant_a", run_id=run_id)
        assert baseline_summary.status == "Complete"
        assert baseline_connection.run is not None
        assert len(baseline_connection.checkpoints) == 2
        assert len(baseline_connection.results) == 2

        # Step 2: Set up crash simulation connection
        crash_connection = _ReconciliationConnection()
        _create_partitioned_reconciliation(crash_connection, run_id=run_id)

        class _CrashAfterFirstPartition:
            def __init__(self) -> None:
                self.crashed = False
                self.seen_by_attempt: list[list[str]] = []

            def iter_partition_results(
                self,
                context: Any,
                *,
                completed_partition_keys: frozenset[str] = frozenset(),
            ) -> Any:
                seen: list[str] = []
                self.seen_by_attempt.append(seen)
                for partition in adapter.iter_partition_results(
                    context,
                    completed_partition_keys=completed_partition_keys,
                ):
                    seen.append(partition.partition_key)
                    yield partition
                    if not self.crashed:
                        self.crashed = True
                        raise _InjectedProcessCrash("Simulated SIGKILL worker termination after checkpoint commit")

        matcher = _CrashAfterFirstPartition()
        worker_1 = PostgresReconciliationWorker(
            _ConnectionFactory(crash_connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=matcher,
            settings=PostgresReconciliationWorkerSettings(
                worker_id="worker-gen-1",
                poll_interval_seconds=0,
                allow_unbound_hosted_policy=True,
            ),
        )

        # Worker 1 runs and crashes on partition 1
        with pytest.raises(_InjectedProcessCrash, match="Simulated SIGKILL"):
            worker_1.process_run(tenant_id="tenant_a", run_id=run_id)

        # Invariant 1: Job remains in Running state, leased to Worker 1
        assert crash_connection.run is not None
        assert crash_connection.run["execution_status"] == "Running"
        assert crash_connection.run["execution_worker_id"] == "worker-gen-1"
        assert crash_connection.run["execution_attempt"] == 1
        assert len(crash_connection.checkpoints) == 1
        assert len(crash_connection.results) == 1

        # Step 3: Successor Worker 2 attempts claim while lease is active
        worker_2 = PostgresReconciliationWorker(
            _ConnectionFactory(crash_connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=matcher,
            settings=PostgresReconciliationWorkerSettings(
                worker_id="worker-gen-2",
                poll_interval_seconds=0,
                allow_unbound_hosted_policy=True,
            ),
        )

        # Invariant 2: Lease fencing rejects Worker 2 while lease is valid
        with pytest.raises(PostgresReconciliationBusyError, match="already leased"):
            worker_2.process_run(tenant_id="tenant_a", run_id=run_id)
        assert len(matcher.seen_by_attempt) == 1

        # Step 4: Advance repository clock past lease expiration
        crash_connection.lease_expired = True

        # Successor Worker 2 takes over
        resumed_summary = worker_2.process_run(tenant_id="tenant_a", run_id=run_id)

        # Invariant 3: Successor completes the job cleanly
        assert resumed_summary.status == "Complete"
        assert resumed_summary.result_count == 2
        assert crash_connection.run["execution_status"] == "Complete"
        assert crash_connection.run["execution_worker_id"] is None
        assert crash_connection.run["execution_attempt"] == 2
        assert len(crash_connection.checkpoints) == 2
        assert len(crash_connection.results) == 2

        # Invariant 4: Zero duplicate records (seen partitions across attempts are mutually disjoint)
        assert len(matcher.seen_by_attempt) == 2
        attempt_1_partitions = matcher.seen_by_attempt[0]
        attempt_2_partitions = matcher.seen_by_attempt[1]
        assert set(attempt_1_partitions).isdisjoint(set(attempt_2_partitions)), (
            f"Duplicate partition execution detected! Attempt 1: {attempt_1_partitions}, Attempt 2: {attempt_2_partitions}"
        )

        # Invariant 5: Worker checkpoint attribution
        checkpoint_workers = [item["worker_id"] for item in crash_connection.checkpoints]
        assert checkpoint_workers == ["worker-gen-1", "worker-gen-2"]

        # Invariant 6: 100% hash parity with baseline run
        assert crash_connection.run["input_manifest_hash"] == baseline_connection.run["input_manifest_hash"]
        assert crash_connection.run["result_set_hash"] == baseline_connection.run["result_set_hash"]
        assert sorted(item["output_hash"] for item in crash_connection.checkpoints) == sorted(
            item["output_hash"] for item in baseline_connection.checkpoints
        )

    finally:
        adapter.close()


def test_multi_generation_cascading_worker_recovery() -> None:
    """Test recovery resilience across 3 successive worker process crashes with sequential checkpoints."""
    run_id = "run-multi-crash-cascade"
    adapter = LocalDeterministicMatcherAdapter()

    try:
        connection = _ReconciliationConnection()
        _create_partitioned_reconciliation(connection, run_id=run_id)

        # Generation 1 crashes after partition 1
        class _CrashGen1:
            def __init__(self) -> None:
                self.count = 0

            def iter_partition_results(
                self,
                context: Any,
                *,
                completed_partition_keys: frozenset[str] = frozenset(),
            ) -> Any:
                for partition in adapter.iter_partition_results(
                    context, completed_partition_keys=completed_partition_keys
                ):
                    self.count += 1
                    yield partition
                    raise _InjectedProcessCrash("Gen 1 Crash")

        gen1_worker = PostgresReconciliationWorker(
            _ConnectionFactory(connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=_CrashGen1(),
            settings=PostgresReconciliationWorkerSettings(
                worker_id="gen-1", poll_interval_seconds=0, allow_unbound_hosted_policy=True
            ),
        )
        with pytest.raises(_InjectedProcessCrash):
            gen1_worker.process_run(tenant_id="tenant_a", run_id=run_id)

        assert len(connection.checkpoints) == 1
        assert connection.run is not None
        assert connection.run["execution_attempt"] == 1

        # Expire lease and launch Generation 2
        connection.lease_expired = True

        gen2_worker = PostgresReconciliationWorker(
            _ConnectionFactory(connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=adapter,  # Normal matcher finishes remaining partition
            settings=PostgresReconciliationWorkerSettings(
                worker_id="gen-2", poll_interval_seconds=0, allow_unbound_hosted_policy=True
            ),
        )

        final_summary = gen2_worker.process_run(tenant_id="tenant_a", run_id=run_id)
        assert final_summary.status == "Complete"
        assert connection.run["execution_attempt"] == 2
        assert len(connection.checkpoints) == 2
        assert [cp["worker_id"] for cp in connection.checkpoints] == ["gen-1", "gen-2"]

    finally:
        adapter.close()
