from __future__ import annotations

import json
from pathlib import Path

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import export_database
from reconforge.domain.jobs import DurableJob, JobStatus
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
    running, claimed = queued.transition(
        JobStatus.RUNNING,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        reason_code="CLAIMED",
    )
    store.persist_transition(queued, running, claimed)
    checkpointed, checkpoint = running.checkpoint(
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:02Z",
        completed_units=2,
        checkpoint_digest="c" * 64,
    )
    store.persist_transition(running, checkpointed, checkpoint)
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
    connection.close()


def test_public_export_contains_sanitized_job_contract_without_hidden_error_text(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    expected = _seed_checkpointed_job(source)
    output = tmp_path / "export"
    export_database(source, output)

    payload = json.loads((output / "finance_workflows.json").read_text(encoding="utf-8"))
    jobs = payload["durable_jobs"]
    transitions = payload["durable_job_transitions"]
    assert jobs[0]["id"] == expected.id
    assert jobs[0]["safe_error_code"] == ""
    assert "error_message" not in jobs[0]
    assert [row["job_version"] for row in transitions] == [1, 2, 3]
