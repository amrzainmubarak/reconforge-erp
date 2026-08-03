from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobLane,
    DurableJobNotFoundError,
    DurableJobWorkerService,
    JobSubmission,
    RoundRobinDurableJobScheduler,
)
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import DurableJobBackpressureError, JobOutputManifest, JobStatus
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def _submission(*, job_id: str = "JOB-APP-1", idempotency_key: str = "request-app-1") -> JobSubmission:
    return JobSubmission(
        job_id=job_id,
        idempotency_scope="tenant/workspace/import",
        idempotency_key=idempotency_key,
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


def test_worker_lease_lifecycle_fences_progress_and_releases_on_completion(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)
    queued, created = application.submit(_submission(), actor_id="scheduler-1")
    replayed, replay_created = application.submit(_submission(), actor_id="scheduler-2")
    assert created is True
    assert replay_created is False
    assert replayed == queued
    with pytest.raises(DurableJobNotFoundError, match="requested tenant scope"):
        application.requeue(
            tenant_id="TENANT-2",
            job_id=queued.id,
            actor_id="scheduler-1",
            occurred_at="2026-07-27T08:00:01Z",
        )

    leased = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:04Z",
    )
    assert leased is not None
    leased = worker.heartbeat(
        leased,
        occurred_at="2026-07-27T08:00:02Z",
        lease_expires_at="2026-07-27T08:00:05Z",
    )
    leased = worker.checkpoint(
        leased,
        occurred_at="2026-07-27T08:00:03Z",
        completed_units=7,
        checkpoint_digest="c" * 64,
    )
    completed = worker.complete(
        leased,
        occurred_at="2026-07-27T08:00:04Z",
        output_manifest=JobOutputManifest(1, "d" * 64, "manifest/job-app-1"),
    )
    assert completed.status is JobStatus.COMPLETED
    assert completed.completed_units == completed.total_units == 10
    assert completed.checkpoint_digest == "c" * 64
    assert connection.execute(
        "SELECT COUNT(*) FROM durable_job_leases WHERE job_id = ?",
        (queued.id,),
    ).fetchone()[0] == 0
    assert [
        row["action"]
        for row in repository.list_lease_events(tenant_id="TENANT-1", job_id=queued.id)
    ] == ["claimed", "renewed", "released"]
    connection.close()


def test_round_robin_scheduler_alternates_exact_lanes_without_cross_lane_claims(tmp_path: Path) -> None:
    database_path = tmp_path / "fair-lanes.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)
    lanes = (
        DurableJobLane("TENANT-FAIR", "WORKSPACE-A", "ENTITY-A"),
        DurableJobLane("TENANT-FAIR", "WORKSPACE-B", "ENTITY-B"),
    )
    for lane_index, lane in enumerate(lanes):
        for ordinal in range(3):
            submission = JobSubmission(
                job_id=f"JOB-FAIR-{lane_index}-{ordinal}",
                idempotency_scope="tenant/workspace/import",
                idempotency_key=f"fair-{lane_index}-{ordinal}",
                tenant_id=lane.tenant_id,
                workspace_id=lane.workspace_id,
                entity_id=lane.entity_id,
                input_digest=(f"{lane_index}{ordinal}" * 32)[:64],
                config_digest="b" * 64,
                worker_version="worker/1.0.0",
                total_units=1,
                retry_ceiling=0,
                created_at=f"2026-07-27T08:00:0{ordinal}Z",
            )
            application.submit(submission, actor_id="scheduler-fair")

    scheduler = RoundRobinDurableJobScheduler(worker, lanes)
    selected_lanes: list[DurableJobLane] = []
    for ordinal in range(6):
        scheduled = scheduler.claim(
            worker_id="worker-fair",
            occurred_at=f"2026-07-27T08:01:{ordinal:02d}Z",
            lease_expires_at=f"2026-07-27T08:02:{ordinal:02d}Z",
        )
        assert scheduled is not None
        selected_lanes.append(scheduled.lane)
        assert scheduled.leased_job.job.workspace_id == scheduled.lane.workspace_id
        assert scheduled.leased_job.job.entity_id == scheduled.lane.entity_id
        worker.cancel(scheduled.leased_job, occurred_at=f"2026-07-27T08:01:{30 + ordinal:02d}Z")

    assert selected_lanes == list(lanes) * 3
    assert scheduler.claim(
        worker_id="worker-fair",
        occurred_at="2026-07-27T08:04:00Z",
        lease_expires_at="2026-07-27T08:05:00Z",
    ) is None
    connection.close()


def test_bounded_submission_is_atomic_idempotent_and_lane_scoped(tmp_path: Path) -> None:
    database_path = tmp_path / "bounded-jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)

    first_submission = _submission(job_id="JOB-BOUND-1", idempotency_key="bounded-1")
    first, created = application.submit_bounded(
        first_submission,
        actor_id="scheduler-1",
        max_queued_jobs=1,
    )
    replayed, replay_created = application.submit_bounded(
        first_submission,
        actor_id="scheduler-2",
        max_queued_jobs=1,
    )
    assert created is True and replay_created is False and replayed == first

    second_submission = _submission(job_id="JOB-BOUND-2", idempotency_key="bounded-2")
    with pytest.raises(DurableJobBackpressureError, match="queue capacity"):
        application.submit_bounded(second_submission, actor_id="scheduler-1", max_queued_jobs=1)
    assert repository.get(tenant_id="TENANT-1", job_id=second_submission.job_id) is None

    sibling_lane = _submission(job_id="JOB-BOUND-3", idempotency_key="bounded-3")
    sibling_lane = replace(sibling_lane, workspace_id="WORKSPACE-2")
    sibling, sibling_created = application.submit_bounded(
        sibling_lane,
        actor_id="scheduler-1",
        max_queued_jobs=1,
    )
    assert sibling_created is True and sibling.workspace_id == "WORKSPACE-2"

    worker = DurableJobWorkerService(repository)
    leased = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:04Z",
    )
    assert leased is not None and leased.job.id == first.id
    retrying = worker.schedule_retry(leased, occurred_at="2026-07-27T08:00:02Z")
    with pytest.raises(DurableJobBackpressureError, match="queue capacity"):
        application.submit_bounded(second_submission, actor_id="scheduler-1", max_queued_jobs=1)
    retry_lease = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-2",
        occurred_at="2026-07-27T08:00:03Z",
        lease_expires_at="2026-07-27T08:00:05Z",
    )
    assert retry_lease is not None and retry_lease.job.id == retrying.id
    worker.cancel(retry_lease, occurred_at="2026-07-27T08:00:04Z")
    second, second_created = application.submit_bounded(
        second_submission,
        actor_id="scheduler-1",
        max_queued_jobs=1,
    )
    assert second_created is True and second.status is JobStatus.QUEUED
    application.cancel(
        tenant_id="TENANT-1",
        job_id=second.id,
        actor_id="scheduler-1",
        occurred_at="2026-07-27T08:00:03Z",
    )
    application.cancel(
        tenant_id="TENANT-1",
        job_id=sibling.id,
        actor_id="scheduler-1",
        occurred_at="2026-07-27T08:00:04Z",
    )
    connection.close()


def test_retry_claim_uses_a_new_fencing_generation(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)
    queued, _ = application.submit(_submission(), actor_id="scheduler-1")
    first = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:03Z",
    )
    assert first is not None
    retrying = worker.schedule_retry(first, occurred_at="2026-07-27T08:00:02Z")
    assert retrying.status is JobStatus.RETRYING
    second = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-2",
        occurred_at="2026-07-27T08:00:03Z",
        lease_expires_at="2026-07-27T08:00:05Z",
    )
    assert second is not None
    assert second.lease.generation == first.lease.generation + 1
    assert second.job.status is JobStatus.RUNNING
    failed = worker.fail(
        second,
        occurred_at="2026-07-27T08:00:04Z",
        safe_error_code="SOURCE_UNAVAILABLE",
    )
    assert failed.status is JobStatus.FAILED
    assert connection.execute(
        "SELECT COUNT(*) FROM durable_job_leases WHERE job_id = ?",
        (queued.id,),
    ).fetchone()[0] == 0
    requeued = application.requeue(
        tenant_id="TENANT-1",
        job_id=failed.id,
        actor_id="scheduler-1",
        occurred_at="2026-07-27T08:00:05Z",
    )
    assert requeued.status is JobStatus.QUEUED
    assert requeued.safe_error_code == ""
    connection.close()


def test_pause_requeue_and_both_cancel_paths_release_or_avoid_leases(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)

    pause_job, _ = application.submit(
        _submission(job_id="JOB-PAUSE-1", idempotency_key="pause-1"),
        actor_id="scheduler-1",
    )
    pause_lease = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-27T08:00:01Z",
        lease_expires_at="2026-07-27T08:00:05Z",
    )
    assert pause_lease is not None and pause_lease.job.id == pause_job.id
    paused = worker.pause(pause_lease, occurred_at="2026-07-27T08:00:02Z")
    assert paused.status is JobStatus.PAUSED
    requeued = application.requeue(
        tenant_id="TENANT-1",
        job_id=paused.id,
        actor_id="scheduler-1",
        occurred_at="2026-07-27T08:00:03Z",
    )
    assert requeued.status is JobStatus.QUEUED

    running_cancel_job, _ = application.submit(
        _submission(job_id="JOB-CANCEL-RUNNING", idempotency_key="cancel-running-1"),
        actor_id="scheduler-1",
    )
    running_cancel_lease = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-2",
        occurred_at="2026-07-27T08:00:04Z",
        lease_expires_at="2026-07-27T08:00:08Z",
    )
    assert running_cancel_lease is not None
    # The older requeued job is deterministically claimed first.
    if running_cancel_lease.job.id == requeued.id:
        worker.cancel(running_cancel_lease, occurred_at="2026-07-27T08:00:05Z")
        running_cancel_lease = worker.claim(
            tenant_id="TENANT-1",
            worker_id="worker-2",
            occurred_at="2026-07-27T08:00:06Z",
            lease_expires_at="2026-07-27T08:00:09Z",
        )
        assert running_cancel_lease is not None
    assert running_cancel_lease.job.id == running_cancel_job.id
    cancelled_running = worker.cancel(
        running_cancel_lease,
        occurred_at="2026-07-27T08:00:07Z",
    )
    assert cancelled_running.status is JobStatus.CANCELLED

    queued_cancel_job, _ = application.submit(
        _submission(job_id="JOB-CANCEL-QUEUED", idempotency_key="cancel-queued-1"),
        actor_id="scheduler-1",
    )
    cancelled_queued = application.cancel(
        tenant_id="TENANT-1",
        job_id=queued_cancel_job.id,
        actor_id="scheduler-1",
        occurred_at="2026-07-27T08:00:08Z",
    )
    assert cancelled_queued.status is JobStatus.CANCELLED
    assert connection.execute("SELECT COUNT(*) FROM durable_job_leases").fetchone()[0] == 0
    connection.close()
