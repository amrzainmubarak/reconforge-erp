from dataclasses import replace
from pathlib import Path

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    GovernedDurableJobApplicationService,
    JobAuthorizationError,
    JobSubmission,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def _submission() -> JobSubmission:
    return JobSubmission(
        job_id="JOB-GOVERNED-1", idempotency_scope="imports", idempotency_key="gov-1",
        tenant_id="tenant-a", workspace_id="workspace-a", entity_id="entity-a",
        input_digest="1" * 64, config_digest="2" * 64, worker_version="worker-v1",
        total_units=2, retry_ceiling=1, created_at="2026-08-02T10:00:00Z",
    )


def _context(*, permissions: set[str], object_owner_id: str | None = None) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="operator", username="operator", user_permissions=permissions,
        tenant_id="tenant-a", workspace_id="workspace-a",
        entity_id="entity-a",
        authorized_tenant_ids=frozenset({"tenant-a"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
        authorized_entity_ids=frozenset({"entity-a"}),
        object_owner_id=object_owner_id,
    )


def _service(tmp_path: Path) -> GovernedDurableJobApplicationService:
    path = tmp_path / "governed-jobs.db"
    run_migrations(path)
    repository = SQLiteDurableJobRepository(connect(path, require_exists=True))
    return GovernedDurableJobApplicationService(DurableJobApplicationService(repository))


def test_governed_submit_denies_before_repository_and_allows_scoped_permission(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(JobAuthorizationError, match="permission_missing"):
        service.submit(
            _submission(), actor_id="operator", policy_context=_context(permissions=set()),
            required_permission="close.manage",
        )
    created, is_new = service.submit(
        _submission(), actor_id="operator", policy_context=_context(permissions={"close.manage"}),
        required_permission="close.manage",
    )
    assert created.id == "JOB-GOVERNED-1" and is_new is True


def test_governed_cancel_rejects_self_approval_and_scope_confusion(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.submit(
        _submission(), actor_id="operator", policy_context=_context(permissions={"close.manage"}),
        required_permission="close.manage",
    )
    with pytest.raises(JobAuthorizationError, match="scope"):
        service.cancel(
            tenant_id="tenant-b", workspace_id="workspace-a", entity_id="entity-a", job_id="JOB-GOVERNED-1",
            actor_id="operator", occurred_at="2026-08-02T10:01:00Z",
            policy_context=_context(permissions={"close.manage"}), required_permission="close.manage",
        )


def test_governed_submit_rejects_organization_scope_confusion(tmp_path: Path) -> None:
    service = _service(tmp_path)
    submission = replace(_submission(), organization_id="organization-b")
    with pytest.raises(JobAuthorizationError, match="organization"):
        service.submit(
            submission,
            actor_id="operator",
            policy_context=_context(permissions={"close.manage"}),
            required_permission="close.manage",
        )


def test_governed_queue_snapshot_and_requeue_bind_scope_and_permission(tmp_path: Path) -> None:
    service = _service(tmp_path)
    submission = _submission()
    service.submit(
        submission,
        actor_id="operator",
        policy_context=_context(permissions={"ops.read"}),
        required_permission="ops.read",
    )

    with pytest.raises(JobAuthorizationError, match="permission_missing"):
        service.queue_snapshot(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            entity_id="entity-a",
            actor_id="operator",
            policy_context=_context(permissions=set()),
            required_permission="ops.read",
        )

    snapshot = service.queue_snapshot(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        actor_id="operator",
        policy_context=_context(permissions={"ops.read"}),
        required_permission="ops.read",
    )
    assert snapshot.queued_count == 1

    worker = DurableJobWorkerService(service._service._repository)
    leased = worker.claim(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        worker_id="worker-for-test",
        occurred_at="2026-08-02T10:02:00Z",
        lease_expires_at="2026-08-02T10:10:00Z",
    )
    assert leased is not None
    failed = worker.fail(
        leased,
        occurred_at="2026-08-02T10:02:30Z",
        safe_error_code="TEST_FAILURE",
    )
    assert failed.status.value == "failed"

    with pytest.raises(JobAuthorizationError, match="persisted job scope"):
        service.requeue(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            entity_id="entity-other",
            job_id=submission.job_id,
            actor_id="operator",
            occurred_at="2026-08-02T10:03:00Z",
            policy_context=replace(
                _context(permissions={"close.manage"}),
                entity_id="entity-other",
                authorized_entity_ids=frozenset({"entity-other"}),
            ),
            required_permission="close.manage",
        )

    requeued = service.requeue(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        job_id=submission.job_id,
        actor_id="operator",
        occurred_at="2026-08-02T10:04:00Z",
        policy_context=_context(permissions={"close.manage"}),
        required_permission="close.manage",
    )
    assert requeued.status.value == "queued"


def test_governed_queue_snapshot_audits_bound_object_action_and_request_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    events: list[dict[str, object]] = []

    def capture(_decision: object, **kwargs: object) -> None:
        events.append(kwargs)

    monkeypatch.setattr("reconforge.application.jobs.audit_policy_decision", capture)
    service.queue_snapshot(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        actor_id="operator",
        policy_context=_context(permissions={"ops.read"}),
        required_permission="ops.read",
        request_id="request-queue-1",
    )

    assert len(events) == 1
    assert events[0]["surface"] == "durable-job.application.read"
    assert events[0]["request_id"] == "request-queue-1"
    context = events[0]["context"]
    assert isinstance(context, PolicyEvaluationContext)
    assert context.object_type == "durable_job_queue"
    assert context.object_id == "queue:tenant-a:workspace-a::entity-a"
    assert context.action == "read"
