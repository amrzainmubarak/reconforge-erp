from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobNotFoundError,
    JobSubmission,
)
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobOutputManifest, JobStatus
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def _submission() -> JobSubmission:
    return JobSubmission(
        job_id="JOB-APP-1",
        idempotency_scope="tenant/workspace/import",
        idempotency_key="request-app-1",
        tenant_id="TENANT-1",
        workspace_id="WORKSPACE-1",
        entity_id="ENTITY-1",
        input_digest="a" * 64,
        config_digest="b" * 64,
        worker_version="worker/1.0.0",
        total_units=10,
        retry_ceiling=1,
        created_at="2026-07-27T08:00:00Z",
    )


def test_application_lifecycle_is_tenant_scoped_resumable_and_manifest_gated(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    service = DurableJobApplicationService(SQLiteDurableJobRepository(connection))

    queued, created = service.submit(_submission(), actor_id="scheduler-1")
    replayed, replay_created = service.submit(_submission(), actor_id="scheduler-2")
    assert created is True
    assert replay_created is False
    assert replayed == queued

    with pytest.raises(DurableJobNotFoundError, match="requested tenant scope"):
        service.start(
            tenant_id="TENANT-2",
            job_id=queued.id,
            actor_id="worker-1",
            occurred_at="2026-07-27T08:00:01Z",
        )

    running = service.start(
        tenant_id="TENANT-1",
        job_id=queued.id,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
    )
    checkpointed = service.checkpoint(
        tenant_id="TENANT-1",
        job_id=running.id,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:02Z",
        completed_units=6,
        checkpoint_digest="c" * 64,
    )
    completed = service.complete(
        tenant_id="TENANT-1",
        job_id=checkpointed.id,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:03Z",
        output_manifest=JobOutputManifest(1, "d" * 64, "manifest/job-app-1"),
    )
    assert completed.status is JobStatus.COMPLETED
    assert completed.completed_units == completed.total_units == 10
    assert completed.checkpoint_digest == "c" * 64
    assert completed.output_manifest == JobOutputManifest(1, "d" * 64, "manifest/job-app-1")
    connection.close()


def test_application_retry_and_failure_paths_are_explicit(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    service = DurableJobApplicationService(SQLiteDurableJobRepository(connection))
    queued, _ = service.submit(_submission(), actor_id="scheduler-1")
    running = service.start(
        tenant_id="TENANT-1",
        job_id=queued.id,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
    )
    retrying = service.schedule_retry(
        tenant_id="TENANT-1",
        job_id=running.id,
        actor_id="worker-1",
        occurred_at="2026-07-27T08:00:02Z",
    )
    assert retrying.status is JobStatus.RETRYING
    assert retrying.retry_count == 1
    running_again = service.start(
        tenant_id="TENANT-1",
        job_id=retrying.id,
        actor_id="worker-2",
        occurred_at="2026-07-27T08:00:03Z",
    )
    failed = service.fail(
        tenant_id="TENANT-1",
        job_id=running_again.id,
        actor_id="worker-2",
        occurred_at="2026-07-27T08:00:04Z",
        safe_error_code="SOURCE_UNAVAILABLE",
    )
    assert failed.status is JobStatus.FAILED
    assert failed.safe_error_code == "SOURCE_UNAVAILABLE"
    requeued = service.requeue(
        tenant_id="TENANT-1",
        job_id=failed.id,
        actor_id="scheduler-1",
        occurred_at="2026-07-27T08:00:05Z",
    )
    assert requeued.status is JobStatus.QUEUED
    assert requeued.safe_error_code == ""
    connection.close()
