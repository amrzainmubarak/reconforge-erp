from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    JobSubmission,
)
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import DurableJob, JobOutputManifest, JobPartitionEffect, JobStatus
from reconforge.infrastructure.sqlite_jobs import (
    SQLiteDurableJobRepository,
    SQLiteJobConflictError,
)

P1_INPUT = "1" * 64
P1_OUTPUT = "2" * 64
P2_INPUT = "3" * 64
P2_OUTPUT = "4" * 64
MANIFEST_DIGEST = "5" * 64


def _submission(job_id: str, key: str) -> JobSubmission:
    return JobSubmission(
        job_id=job_id,
        idempotency_scope="tenant/workspace/deterministic-manifest",
        idempotency_key=key,
        tenant_id="TENANT-1",
        workspace_id="WORKSPACE-1",
        entity_id="ENTITY-1",
        input_digest="a" * 64,
        config_digest="b" * 64,
        worker_version="manifest-worker/1.0.0",
        total_units=2,
        retry_ceiling=2,
        created_at="2026-07-27T08:00:00Z",
    )


def _semantic_effects(effects: list[JobPartitionEffect]) -> list[tuple[object, ...]]:
    return [
        (
            effect.partition_key,
            effect.ordinal,
            effect.completed_units,
            effect.input_digest,
            effect.output_digest,
            effect.effect_reference,
        )
        for effect in effects
    ]


def _finish_two_partition_workload(
    database_path: Path,
    *,
    job_id: str,
    key: str,
    restart_after_first: bool,
) -> tuple[DurableJob, list[JobPartitionEffect], list[str]]:
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)
    queued, _ = application.submit(_submission(job_id, key), actor_id="scheduler-1")
    claimed = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:03Z" if restart_after_first else "2026-07-27T08:00:10Z",
    )
    assert claimed is not None
    leased = worker.commit_partition(
        claimed,
        partition_key="partition/0001",
        ordinal=1,
        completed_units=1,
        input_digest=P1_INPUT,
        output_digest=P1_OUTPUT,
        effect_reference="effect/0001",
        occurred_at="2026-07-27T08:00:02Z",
    )

    if restart_after_first:
        connection.close()
        connection = connect(database_path, require_exists=True)
        repository = SQLiteDurableJobRepository(connection)
        worker = DurableJobWorkerService(repository)
        resumed = worker.claim(
            tenant_id="TENANT-1",
            worker_id="worker-2",
            occurred_at="2026-07-27T08:00:03Z",
            lease_expires_at="2026-07-27T08:00:06Z",
        )
        assert resumed is not None
        leased = resumed

    assert [effect.partition_key for effect in worker.completed_effects(leased)] == ["partition/0001"]
    final_time = "2026-07-27T08:00:04Z" if restart_after_first else "2026-07-27T08:00:03Z"
    completed = worker.complete_partition(
        leased,
        partition_key="partition/0002",
        ordinal=2,
        input_digest=P2_INPUT,
        output_digest=P2_OUTPUT,
        effect_reference="effect/0002",
        occurred_at=final_time,
        output_manifest=JobOutputManifest(1, MANIFEST_DIGEST, "manifest/two-partition-v1"),
    )
    effects = repository.list_partition_effects(tenant_id="TENANT-1", job_id=queued.id)
    transitions = [
        str(row["reason_code"])
        for row in repository.list_transitions(tenant_id="TENANT-1", job_id=queued.id)
    ]
    connection.close()
    return completed, effects, transitions


def test_restarted_workload_skips_committed_effect_and_matches_uninterrupted_digest(tmp_path: Path) -> None:
    uninterrupted, uninterrupted_effects, uninterrupted_transitions = _finish_two_partition_workload(
        tmp_path / "uninterrupted.db",
        job_id="JOB-UNINTERRUPTED",
        key="uninterrupted-1",
        restart_after_first=False,
    )
    resumed, resumed_effects, resumed_transitions = _finish_two_partition_workload(
        tmp_path / "resumed.db",
        job_id="JOB-RESUMED",
        key="resumed-1",
        restart_after_first=True,
    )

    assert uninterrupted.status is resumed.status is JobStatus.COMPLETED
    assert uninterrupted.output_manifest == resumed.output_manifest
    assert _semantic_effects(uninterrupted_effects) == _semantic_effects(resumed_effects)
    assert len(uninterrupted_effects) == len(resumed_effects) == 2
    assert uninterrupted_transitions == ["CREATED", "CLAIMED", "CHECKPOINTED", "FINISHED"]
    assert resumed_transitions == [
        "CREATED",
        "CLAIMED",
        "CHECKPOINTED",
        "LEASE_TAKEOVER",
        "FINISHED",
    ]


def test_effect_and_checkpoint_roll_back_together_on_transition_failure(tmp_path: Path) -> None:
    database_path = tmp_path / "rollback.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)
    queued, _ = application.submit(_submission("JOB-ROLLBACK", "rollback-1"), actor_id="scheduler-1")
    leased = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:05Z",
    )
    assert leased is not None
    connection.execute(
        """
        CREATE TRIGGER reject_effect_checkpoint_transition
        BEFORE INSERT ON durable_job_transitions
        WHEN NEW.reason_code = 'CHECKPOINTED'
        BEGIN
            SELECT RAISE(ABORT, 'injected checkpoint transition failure');
        END
        """
    )
    connection.commit()

    with pytest.raises(SQLiteJobConflictError, match="partition effect conflicts"):
        worker.commit_partition(
            leased,
            partition_key="partition/0001",
            ordinal=1,
            completed_units=1,
            input_digest=P1_INPUT,
            output_digest=P1_OUTPUT,
            effect_reference="effect/0001",
            occurred_at="2026-07-27T08:00:02Z",
        )
    stored = repository.get(tenant_id="TENANT-1", job_id=queued.id)
    assert stored == leased.job
    assert repository.list_partition_effects(tenant_id="TENANT-1", job_id=queued.id) == []
    assert connection.execute(
        "SELECT COUNT(*) FROM durable_job_leases WHERE job_id = ?",
        (queued.id,),
    ).fetchone()[0] == 1
    connection.close()


def test_partition_effect_rows_are_database_immutable(tmp_path: Path) -> None:
    database_path = tmp_path / "immutable.db"
    completed, effects, _ = _finish_two_partition_workload(
        database_path,
        job_id="JOB-IMMUTABLE",
        key="immutable-1",
        restart_after_first=False,
    )
    assert completed.status is JobStatus.COMPLETED and len(effects) == 2
    connection = connect(database_path, require_exists=True)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE durable_job_partition_effects SET output_digest = ? WHERE job_id = ?",
            ("f" * 64, completed.id),
        )
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("DELETE FROM durable_job_partition_effects WHERE job_id = ?", (completed.id,))
    connection.rollback()
    connection.close()
