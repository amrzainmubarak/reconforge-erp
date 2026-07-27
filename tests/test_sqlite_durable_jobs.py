from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import DurableJob, JobOutputManifest, JobStatus
from reconforge.infrastructure.sqlite_jobs import (
    SQLiteDurableJobRepository,
    SQLiteJobConflictError,
    SQLiteJobRepositoryError,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
T0 = "2026-07-27T08:00:00Z"


def _job(*, job_id: str = "JOB-001", input_digest: str = DIGEST_A) -> DurableJob:
    return DurableJob.queued(
        job_id=job_id,
        idempotency_scope="tenant/workspace/import",
        idempotency_key="request-001",
        tenant_id="TENANT-1",
        workspace_id="WORKSPACE-1",
        entity_id="ENTITY-1",
        input_digest=input_digest,
        config_digest=DIGEST_B,
        worker_version="worker/1.0.0",
        total_units=10,
        retry_ceiling=2,
        created_at=T0,
    )


@pytest.fixture
def repository(tmp_path: Path) -> tuple[SQLiteDurableJobRepository, sqlite3.Connection]:
    database_path = tmp_path / "jobs.db"
    result = run_migrations(database_path)
    assert result.current_version == 22
    connection = connect(database_path)
    return SQLiteDurableJobRepository(connection), connection


def test_submission_is_atomic_idempotent_and_tenant_scoped(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    created, was_created = store.create_or_get(_job(), actor_id="scheduler-1")
    replayed, replay_created = store.create_or_get(_job(job_id="JOB-REPLAY"), actor_id="scheduler-2")

    assert was_created is True
    assert replay_created is False
    assert replayed == created
    assert store.get(tenant_id="TENANT-1", job_id=created.id) == created
    assert store.get(tenant_id="TENANT-2", job_id=created.id) is None
    transitions = store.list_transitions(tenant_id="TENANT-1", job_id=created.id)
    assert [(row["job_version"], row["from_status"], row["to_status"]) for row in transitions] == [
        (1, "", "queued")
    ]
    assert transitions[0]["actor_id"] == "scheduler-1"
    connection.close()


def test_idempotency_key_rejects_changed_inputs(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    store.create_or_get(_job(), actor_id="scheduler-1")
    with pytest.raises(SQLiteJobConflictError, match="different job submission"):
        store.create_or_get(_job(job_id="JOB-OTHER", input_digest=DIGEST_C), actor_id="scheduler-1")
    assert connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0] == 1
    connection.close()


def test_transition_checkpoint_and_completion_round_trip_atomically(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    queued, _ = store.create_or_get(_job(), actor_id="scheduler-1")
    claim = store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:10Z",
    )
    assert claim is not None
    running, lease = claim
    checkpointed, checkpoint = running.checkpoint(
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:02Z",
        completed_units=4,
        checkpoint_digest=DIGEST_C,
    )
    store.persist_owned_transition(
        running,
        checkpointed,
        checkpoint,
        lease=lease,
        release_lease=False,
    )
    completed, finished = checkpointed.transition(
        JobStatus.COMPLETED,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:03Z",
        reason_code="FINISHED",
        completed_units=10,
        output_manifest=JobOutputManifest(1, DIGEST_C, "manifest/output-1"),
    )
    store.persist_owned_transition(
        checkpointed,
        completed,
        finished,
        lease=lease,
        release_lease=True,
    )

    assert store.get(tenant_id="TENANT-1", job_id=completed.id) == completed
    assert [row["job_version"] for row in store.list_transitions(tenant_id="TENANT-1", job_id=completed.id)] == [
        1,
        2,
        3,
        4,
    ]
    connection.close()


def test_stale_version_and_transition_insert_failure_roll_back_job_state(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    queued, _ = store.create_or_get(_job(), actor_id="scheduler-1")
    claim = store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:10Z",
    )
    assert claim is not None
    running, lease = claim
    checkpointed, checkpoint_event = running.checkpoint(
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:02Z",
        completed_units=2,
        checkpoint_digest=DIGEST_C,
    )
    store.persist_owned_transition(
        running,
        checkpointed,
        checkpoint_event,
        lease=lease,
        release_lease=False,
    )
    with pytest.raises(SQLiteJobConflictError, match="changed before"):
        store.persist_owned_transition(
            running,
            checkpointed,
            checkpoint_event,
            lease=lease,
            release_lease=False,
        )

    connection.execute(
        """
        CREATE TRIGGER reject_job_pause
        BEFORE INSERT ON durable_job_transitions
        WHEN NEW.to_status = 'paused'
        BEGIN
            SELECT RAISE(ABORT, 'injected transition evidence failure');
        END
        """
    )
    connection.commit()
    paused, pause_event = checkpointed.transition(
        JobStatus.PAUSED,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:03Z",
        reason_code="OPERATOR_PAUSE",
    )
    with pytest.raises(SQLiteJobConflictError, match="leased transition conflicts"):
        store.persist_owned_transition(
            checkpointed,
            paused,
            pause_event,
            lease=lease,
            release_lease=True,
        )
    assert store.get(tenant_id="TENANT-1", job_id=running.id) == checkpointed
    assert len(store.list_transitions(tenant_id="TENANT-1", job_id=running.id)) == 3
    assert connection.execute("SELECT COUNT(*) FROM durable_job_leases").fetchone()[0] == 1
    connection.close()


def test_repository_refuses_ambiguous_outer_transaction(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    connection.execute("BEGIN")
    with pytest.raises(SQLiteJobRepositoryError, match="unambiguous transaction"):
        store.create_or_get(_job(), actor_id="scheduler-1")
    connection.rollback()
    connection.close()


def test_transition_evidence_is_immutable(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    job, _ = store.create_or_get(_job(), actor_id="scheduler-1")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE durable_job_transitions SET actor_id = 'tampered' WHERE job_id = ?",
            (job.id,),
        )
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("DELETE FROM durable_job_transitions WHERE job_id = ?", (job.id,))
    connection.rollback()
    connection.close()


def test_corrupt_stored_digest_fails_closed_at_repository_boundary(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    job, _ = store.create_or_get(_job(), actor_id="scheduler-1")
    connection.execute(
        "UPDATE durable_jobs SET input_digest = ? WHERE id = ?",
        ("A" * 64, job.id),
    )
    connection.commit()
    with pytest.raises(SQLiteJobRepositoryError, match="Stored durable-job state is invalid"):
        store.get(tenant_id="TENANT-1", job_id=job.id)
    connection.close()


def test_version_20_upgrade_applies_only_durable_job_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "upgrade.db"
    before = run_migrations(database_path, target_version=20)
    assert before.current_version == 20
    upgraded = run_migrations(database_path)
    assert upgraded.applied_versions == [21, 22]
    connection = connect(database_path, require_exists=True)
    tables = {
        str(row["name"])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert {
        "durable_jobs",
        "durable_job_transitions",
        "durable_job_leases",
        "durable_job_lease_events",
    } <= tables
    connection.close()


def test_lease_heartbeat_expiry_takeover_and_fencing_are_atomic(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    queued, _ = store.create_or_get(_job(), actor_id="scheduler-1")
    first_claim = store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:03Z",
    )
    assert first_claim is not None
    running, lease_one = first_claim
    assert running.status is JobStatus.RUNNING
    assert lease_one.generation == 1
    assert store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-2",
        occurred_at="2026-07-27T08:00:02Z",
        lease_expires_at="2026-07-27T08:00:04Z",
    ) is None

    renewed = store.renew_lease(
        lease_one,
        occurred_at="2026-07-27T08:00:02Z",
        lease_expires_at="2026-07-27T08:00:04Z",
    )
    stale_checkpointed, stale_event = running.checkpoint(
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:03Z",
        completed_units=2,
        checkpoint_digest=DIGEST_C,
    )
    takeover = store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-2",
        occurred_at="2026-07-27T08:00:04Z",
        lease_expires_at="2026-07-27T08:00:06Z",
    )
    assert takeover is not None
    reclaimed, lease_two = takeover
    assert reclaimed.status is JobStatus.RUNNING
    assert reclaimed.version == running.version + 1
    assert lease_two.generation == renewed.generation + 1 == 2
    with pytest.raises(SQLiteJobConflictError, match="ownership changed or expired"):
        store.persist_owned_transition(
            running,
            stale_checkpointed,
            stale_event,
            lease=renewed,
            release_lease=False,
        )

    checkpointed, checkpoint_event = reclaimed.checkpoint(
        actor_id="worker-2",
        occurred_at="2026-07-27T08:00:05Z",
        completed_units=4,
        checkpoint_digest=DIGEST_C,
    )
    store.persist_owned_transition(
        reclaimed,
        checkpointed,
        checkpoint_event,
        lease=lease_two,
        release_lease=False,
    )
    assert store.get(tenant_id="TENANT-1", job_id=queued.id) == checkpointed
    lease_actions = [
        row["action"]
        for row in store.list_lease_events(tenant_id="TENANT-1", job_id=queued.id)
    ]
    assert lease_actions == ["claimed", "renewed", "taken_over"]
    connection.close()


def test_claim_rolls_back_state_and_lease_when_lease_evidence_fails(
    repository: tuple[SQLiteDurableJobRepository, sqlite3.Connection],
) -> None:
    store, connection = repository
    queued, _ = store.create_or_get(_job(), actor_id="scheduler-1")
    connection.execute(
        """
        CREATE TRIGGER reject_lease_claim_evidence
        BEFORE INSERT ON durable_job_lease_events
        WHEN NEW.action = 'claimed'
        BEGIN
            SELECT RAISE(ABORT, 'injected lease evidence failure');
        END
        """
    )
    connection.commit()
    with pytest.raises(SQLiteJobRepositoryError, match="Unable to claim durable job"):
        store.claim_next(
            tenant_id="TENANT-1",
            worker_id="worker-1",
            occurred_at="2026-07-27T08:00:01Z",
            lease_expires_at="2026-07-27T08:00:03Z",
        )
    assert store.get(tenant_id="TENANT-1", job_id=queued.id) == queued
    assert len(store.list_transitions(tenant_id="TENANT-1", job_id=queued.id)) == 1
    assert connection.execute("SELECT COUNT(*) FROM durable_job_leases").fetchone()[0] == 0
    connection.close()


def test_process_restart_takes_over_from_last_committed_checkpoint(tmp_path: Path) -> None:
    database_path = tmp_path / "restart.db"
    run_migrations(database_path)
    first_connection = connect(database_path, require_exists=True)
    first_store = SQLiteDurableJobRepository(first_connection)
    queued, _ = first_store.create_or_get(_job(), actor_id="scheduler-1")
    first_claim = first_store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-before-crash",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:03Z",
    )
    assert first_claim is not None
    running, first_lease = first_claim
    checkpointed, event = running.checkpoint(
        actor_id=first_lease.owner_id,
        occurred_at="2026-07-27T08:00:02Z",
        completed_units=6,
        checkpoint_digest=DIGEST_C,
    )
    first_store.persist_owned_transition(
        running,
        checkpointed,
        event,
        lease=first_lease,
        release_lease=False,
    )
    first_connection.close()

    restarted_connection = connect(database_path, require_exists=True)
    restarted_store = SQLiteDurableJobRepository(restarted_connection)
    takeover = restarted_store.claim_next(
        tenant_id="TENANT-1",
        worker_id="worker-after-crash",
        occurred_at="2026-07-27T08:00:03Z",
        lease_expires_at="2026-07-27T08:00:06Z",
    )
    assert takeover is not None
    resumed, second_lease = takeover
    assert resumed.id == queued.id
    assert resumed.completed_units == 6
    assert resumed.checkpoint_digest == DIGEST_C
    assert second_lease.generation == first_lease.generation + 1
    assert [
        row["reason_code"]
        for row in restarted_store.list_transitions(tenant_id="TENANT-1", job_id=queued.id)
    ] == ["CREATED", "CLAIMED", "CHECKPOINTED", "LEASE_TAKEOVER"]
    restarted_connection.close()
