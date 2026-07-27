from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.domain.jobs import (
    ALLOWED_TRANSITIONS,
    DurableJob,
    JobInvariantError,
    JobOutputManifest,
    JobStatus,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
T0 = "2026-07-27T08:00:00Z"
T1 = "2026-07-27T08:00:01Z"
T2 = "2026-07-27T08:00:02Z"


def _queued(*, retry_ceiling: int = 2, total_units: int = 10) -> DurableJob:
    return DurableJob.queued(
        job_id="JOB-001",
        idempotency_scope="tenant/workspace/import",
        idempotency_key="request-001",
        tenant_id="TENANT-1",
        workspace_id="WORKSPACE-1",
        entity_id="ENTITY-1",
        input_digest=DIGEST_A,
        config_digest=DIGEST_B,
        worker_version="worker/1.0.0",
        total_units=total_units,
        retry_ceiling=retry_ceiling,
        created_at=T0,
    )


def _running(*, retry_ceiling: int = 2, total_units: int = 10) -> DurableJob:
    running, _ = _queued(retry_ceiling=retry_ceiling, total_units=total_units).transition(
        JobStatus.RUNNING,
        actor_id="worker-1",
        occurred_at=T1,
        reason_code="CLAIMED",
    )
    return running


def test_queued_factory_preserves_scope_digests_and_integer_progress() -> None:
    job = _queued()
    assert job.status is JobStatus.QUEUED
    assert job.version == 1
    assert job.completed_units == 0
    assert job.total_units == 10
    assert job.output_manifest is None
    assert job.input_digest == DIGEST_A
    assert job.config_digest == DIGEST_B


@given(from_status=st.sampled_from(list(JobStatus)), to_status=st.sampled_from(list(JobStatus)))
def test_transition_matrix_fails_closed(from_status: JobStatus, to_status: JobStatus) -> None:
    base = _queued()
    if from_status is JobStatus.COMPLETED:
        base = replace(
            base,
            status=from_status,
            completed_units=base.total_units,
            completed_at=T1,
            started_at=T1,
            output_manifest=JobOutputManifest(1, DIGEST_C, "manifest/output-1"),
        )
    elif from_status is JobStatus.FAILED:
        base = replace(base, status=from_status, safe_error_code="SAFE_FAILURE", started_at=T1)
    elif from_status in {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.RETRYING}:
        base = replace(base, status=from_status, started_at=T1)
    else:
        base = replace(base, status=from_status)

    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        with pytest.raises(JobInvariantError, match="is not allowed"):
            base.transition(
                to_status,
                actor_id="worker-1",
                occurred_at=T2,
                reason_code="TEST_TRANSITION",
            )


def test_completion_requires_full_progress_manifest_and_timestamp() -> None:
    running = _running()
    with pytest.raises(JobInvariantError, match="completed jobs require"):
        running.transition(
            JobStatus.COMPLETED,
            actor_id="worker-1",
            occurred_at=T2,
            reason_code="FINISHED",
            completed_units=10,
        )

    completed, event = running.transition(
        JobStatus.COMPLETED,
        actor_id="worker-1",
        occurred_at=T2,
        reason_code="FINISHED",
        completed_units=10,
        checkpoint_digest=DIGEST_C,
        output_manifest=JobOutputManifest(1, DIGEST_C, "manifest/output-1"),
    )
    assert completed.status is JobStatus.COMPLETED
    assert completed.completed_at == T2
    assert completed.version == 3
    assert event.job_version == 3
    assert event.from_status is JobStatus.RUNNING
    assert event.to_status is JobStatus.COMPLETED


def test_retry_ceiling_and_safe_failure_code_are_enforced() -> None:
    running = _running(retry_ceiling=1)
    retrying, _ = running.transition(
        JobStatus.RETRYING,
        actor_id="worker-1",
        occurred_at=T2,
        reason_code="TRANSIENT_FAILURE",
    )
    assert retrying.retry_count == 1
    running_again, _ = retrying.transition(
        JobStatus.RUNNING,
        actor_id="worker-2",
        occurred_at="2026-07-27T08:00:03Z",
        reason_code="RETRY_CLAIMED",
    )
    with pytest.raises(JobInvariantError, match="retry ceiling"):
        running_again.transition(
            JobStatus.RETRYING,
            actor_id="worker-2",
            occurred_at="2026-07-27T08:00:04Z",
            reason_code="TRANSIENT_FAILURE",
        )
    with pytest.raises(JobInvariantError, match="safe error code"):
        running.transition(
            JobStatus.FAILED,
            actor_id="worker-1",
            occurred_at=T2,
            reason_code="TERMINAL_FAILURE",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input_digest", "ABC", "lowercase SHA-256"),
        ("completed_units", 11, "outside its declared total"),
        ("completed_units", -1, "outside its declared total"),
        ("safe_error_code", "secret error text", "invalid format"),
        ("created_at", "2026-07-27T08:00:00+00:00", "canonical UTC"),
    ],
)
def test_invalid_financially_relevant_or_sensitive_fields_fail_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(JobInvariantError, match=message):
        replace(_queued(), **{field: value})


def test_transition_rejects_time_reversal_and_non_integer_progress() -> None:
    running = _running()
    with pytest.raises(JobInvariantError, match="cannot precede"):
        running.transition(
            JobStatus.PAUSED,
            actor_id="worker-1",
            occurred_at=T0,
            reason_code="OPERATOR_PAUSE",
        )
    with pytest.raises(JobInvariantError, match="integer units"):
        replace(running, completed_units=True)
    with pytest.raises(JobInvariantError, match="outside its declared total"):
        replace(running, completed_units=11)


def test_checkpoint_is_monotonic_bounded_and_digest_addressed() -> None:
    running = _running(total_units=10)
    checkpointed, event = running.checkpoint(
        actor_id="worker-1",
        occurred_at=T2,
        completed_units=4,
        checkpoint_digest=DIGEST_C,
    )
    assert checkpointed.status is JobStatus.RUNNING
    assert checkpointed.completed_units == 4
    assert checkpointed.checkpoint_digest == DIGEST_C
    assert checkpointed.version == running.version + 1
    assert event.from_status is event.to_status is JobStatus.RUNNING
    assert event.reason_code == "CHECKPOINTED"

    with pytest.raises(JobInvariantError, match="backwards"):
        checkpointed.checkpoint(
            actor_id="worker-1",
            occurred_at="2026-07-27T08:00:03Z",
            completed_units=3,
            checkpoint_digest=DIGEST_C,
        )
    with pytest.raises(JobInvariantError, match="precede full completion"):
        checkpointed.checkpoint(
            actor_id="worker-1",
            occurred_at="2026-07-27T08:00:03Z",
            completed_units=10,
            checkpoint_digest=DIGEST_C,
        )
