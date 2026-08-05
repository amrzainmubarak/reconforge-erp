from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    GovernedDurableJobWorkerService,
    JobAuthorizationError,
    JobSubmission,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def _submission() -> JobSubmission:
    return JobSubmission(
        job_id="JOB-GOVERNED-WORKER-1",
        idempotency_scope="tenant/workspace/match",
        idempotency_key="governed-worker-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        input_digest="a" * 64,
        config_digest="b" * 64,
        worker_version="worker-v1",
        total_units=1,
        retry_ceiling=0,
        created_at="2026-08-05T10:00:00Z",
    )


def _context(*, permissions: set[str], principal_type: str = "service_account", tenant: str = "tenant-a", workspace: str = "workspace-a") -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="svc-match-worker",
        username="svc-match-worker",
        user_permissions=permissions,
        principal_type=principal_type,  # type: ignore[arg-type]
        tenant_id=tenant,
        workspace_id=workspace,
        authorized_tenant_ids=frozenset({"tenant-a"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
    )


def _services(tmp_path: Path) -> tuple[DurableJobApplicationService, GovernedDurableJobWorkerService, SQLiteDurableJobRepository]:
    path = tmp_path / "governed-worker.db"
    run_migrations(path)
    repository = SQLiteDurableJobRepository(connect(path, require_exists=True))
    application = DurableJobApplicationService(repository)
    governed = GovernedDurableJobWorkerService(DurableJobWorkerService(repository))
    return application, governed, repository


def test_governed_worker_denies_missing_permission_before_claim(tmp_path: Path) -> None:
    application, worker, repository = _services(tmp_path)
    application.submit(_submission(), actor_id="scheduler")

    with pytest.raises(JobAuthorizationError, match="permission_missing"):
        worker.claim(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            entity_id="entity-a",
            worker_id="svc-match-worker",
            occurred_at="2026-08-05T10:00:01Z",
            lease_expires_at="2026-08-05T10:05:01Z",
            policy_context=_context(permissions=set()),
            required_permission="match.run",
        )

    job = repository.get(tenant_id="tenant-a", job_id="JOB-GOVERNED-WORKER-1")
    assert job is not None and job.status.value == "queued"
    assert repository.list_lease_events(tenant_id="tenant-a", job_id=job.id) == []


def test_governed_worker_requires_service_identity_and_matching_scope(tmp_path: Path) -> None:
    application, worker, repository = _services(tmp_path)
    application.submit(_submission(), actor_id="scheduler")

    common = dict(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        worker_id="svc-match-worker",
        occurred_at="2026-08-05T10:00:01Z",
        lease_expires_at="2026-08-05T10:05:01Z",
        required_permission="match.run",
    )
    with pytest.raises(JobAuthorizationError, match="service-account"):
        worker.claim(**common, policy_context=_context(permissions={"match.run"}, principal_type="user"))
    with pytest.raises(JobAuthorizationError, match="scope"):
        worker.claim(
            **common,
            policy_context=_context(permissions={"match.run"}, workspace="workspace-other"),
        )
    assert repository.list_lease_events(tenant_id="tenant-a", job_id="JOB-GOVERNED-WORKER-1") == []


def test_governed_worker_claims_only_after_scoped_service_policy_allows(tmp_path: Path) -> None:
    application, worker, repository = _services(tmp_path)
    application.submit(_submission(), actor_id="scheduler")

    leased = worker.claim(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        worker_id="svc-match-worker",
        occurred_at="2026-08-05T10:00:01Z",
        lease_expires_at="2026-08-05T10:05:01Z",
        policy_context=_context(permissions={"match.run"}),
        required_permission="match.run",
        request_id="req-governed-worker",
    )
    assert leased is not None
    assert leased.job.tenant_id == "tenant-a"
    assert [event["action"] for event in repository.list_lease_events(tenant_id="tenant-a", job_id=leased.job.id)] == [
        "claimed"
    ]
