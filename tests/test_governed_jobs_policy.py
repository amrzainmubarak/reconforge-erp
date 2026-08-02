from pathlib import Path

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
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
        authorized_tenant_ids=frozenset({"tenant-a"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
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
            tenant_id="tenant-b", workspace_id="workspace-a", job_id="JOB-GOVERNED-1",
            actor_id="operator", occurred_at="2026-08-02T10:01:00Z",
            policy_context=_context(permissions={"close.manage"}), required_permission="close.manage",
        )
