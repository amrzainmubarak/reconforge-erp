from __future__ import annotations

import json
from pathlib import Path

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import export_database
from reconforge.domain.jobs import DurableJob, JobPartitionEffect
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def _seed_checkpointed_job(database_path: Path) -> DurableJob:
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    store = SQLiteDurableJobRepository(connection)
    queued, _ = store.create_or_get(
        DurableJob.queued(
            job_id="JOB-BACKUP-1",
            idempotency_scope="tenant/workspace/export",
            idempotency_key="backup-request-1",
            tenant_id="TENANT-1",
            workspace_id="WORKSPACE-1",
            input_digest="a" * 64,
            config_digest="b" * 64,
            worker_version="worker/1.0.0",
            total_units=5,
            retry_ceiling=2,
            created_at="2026-07-27T08:00:00Z",
        ),
        actor_id="scheduler-1",
    )
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
        completed_units=2,
        checkpoint_digest="c" * 64,
    )
    store.persist_owned_effect_transition(
        running,
        checkpointed,
        checkpoint,
        JobPartitionEffect(
            job_id=running.id,
            partition_key="partition/0001",
            ordinal=1,
            completed_units=2,
            input_digest="d" * 64,
            output_digest="c" * 64,
            effect_reference="effect/0001",
            committed_at="2026-07-27T08:00:02Z",
        ),
        lease=lease,
        release_lease=False,
    )
    connection.close()
    return checkpointed


def test_backup_restore_preserves_job_and_append_only_transition_history(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    expected = _seed_checkpointed_job(source)
    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)

    connection = connect(restored, require_exists=True)
    store = SQLiteDurableJobRepository(connection)
    assert store.get(tenant_id="TENANT-1", job_id=expected.id) == expected
    transitions = store.list_transitions(tenant_id="TENANT-1", job_id=expected.id)
    assert [row["job_version"] for row in transitions] == [1, 2, 3]
    assert transitions[-1]["reason_code"] == "CHECKPOINTED"
    lease_events = store.list_lease_events(tenant_id="TENANT-1", job_id=expected.id)
    assert [row["action"] for row in lease_events] == ["claimed"]
    effects = store.list_partition_effects(tenant_id="TENANT-1", job_id=expected.id)
    assert [(effect.partition_key, effect.completed_units) for effect in effects] == [("partition/0001", 2)]
    lease_row = connection.execute(
        "SELECT owner_id, generation, expires_at FROM durable_job_leases WHERE job_id = ?",
        (expected.id,),
    ).fetchone()
    assert dict(lease_row) == {
        "owner_id": "worker-1",
        "generation": 1,
        "expires_at": "2026-07-27T08:00:10Z",
    }
    connection.close()


def test_public_export_contains_sanitized_job_contract_without_hidden_error_text(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    expected = _seed_checkpointed_job(source)
    output = tmp_path / "export"
    export_database(source, output)

    payload = json.loads((output / "finance_workflows.json").read_text(encoding="utf-8"))
    jobs = payload["durable_jobs"]
    transitions = payload["durable_job_transitions"]
    leases = payload["durable_job_leases"]
    lease_events = payload["durable_job_lease_events"]
    effects = payload["durable_job_partition_effects"]
    assert jobs[0]["id"] == expected.id
    assert jobs[0]["safe_error_code"] == ""
    assert "error_message" not in jobs[0]
    assert [row["job_version"] for row in transitions] == [1, 2, 3]
    assert leases[0]["owner_id"] == "worker-1"
    assert lease_events[0]["action"] == "claimed"
    assert effects[0]["partition_key"] == "partition/0001"
    assert effects[0]["output_digest"] == "c" * 64
