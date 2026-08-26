from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import reconforge.application.jobs as jobs_module
from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    GovernedDurableJobWorkerService,
    JobAuthorizationError,
    JobSubmission,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobOutputManifest
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


def _context(
    *,
    permissions: set[str],
    principal_type: str = "service_account",
    tenant: str = "tenant-a",
    workspace: str = "workspace-a",
    entity: str | None = "entity-a",
) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="svc-match-worker",
        username="svc-match-worker",
        user_permissions=permissions,
        principal_type=principal_type,  # type: ignore[arg-type]
        tenant_id=tenant,
        workspace_id=workspace,
        entity_id=entity,
        authorized_tenant_ids=frozenset({"tenant-a"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
        authorized_entity_ids=frozenset({"entity-a"}),
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
    with pytest.raises(JobAuthorizationError, match="entity"):
        worker.claim(**common, policy_context=_context(permissions={"match.run"}, entity=None))
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


def test_governed_worker_rechecks_policy_before_lease_extension_and_completion(tmp_path: Path) -> None:
    application, worker, repository = _services(tmp_path)
    application.submit(_submission(), actor_id="scheduler")
    allowed = _context(permissions={"match.run"})
    leased = worker.claim(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        worker_id="svc-match-worker",
        occurred_at="2026-08-05T10:00:01Z",
        lease_expires_at="2026-08-05T10:05:01Z",
        policy_context=allowed,
        required_permission="match.run",
    )
    assert leased is not None

    with pytest.raises(JobAuthorizationError, match="permission_missing"):
        worker.heartbeat(
            leased,
            occurred_at="2026-08-05T10:00:02Z",
            lease_expires_at="2026-08-05T10:06:01Z",
            policy_context=_context(permissions=set()),
            required_permission="match.run",
        )
    assert [event["action"] for event in repository.list_lease_events(tenant_id="tenant-a", job_id=leased.job.id)] == [
        "claimed"
    ]

    renewed = worker.heartbeat(
        leased,
        occurred_at="2026-08-05T10:00:03Z",
        lease_expires_at="2026-08-05T10:06:01Z",
        policy_context=allowed,
        required_permission="match.run",
    )
    assert renewed.lease.expires_at == "2026-08-05T10:06:01Z"

    with pytest.raises(JobAuthorizationError, match="permission_missing"):
        worker.complete(
            renewed,
            occurred_at="2026-08-05T10:00:04Z",
            output_manifest=JobOutputManifest(1, "d" * 64, "manifest/governed-worker-1"),
            policy_context=_context(permissions=set()),
            required_permission="match.run",
        )
    current = repository.get(tenant_id="tenant-a", job_id=renewed.job.id)
    assert current is not None and current.status.value == "running"

    completed = worker.complete(
        renewed,
        occurred_at="2026-08-05T10:00:05Z",
        output_manifest=JobOutputManifest(1, "d" * 64, "manifest/governed-worker-1"),
        policy_context=allowed,
        required_permission="match.run",
    )
    assert completed.status.value == "completed"


def test_governed_worker_audit_binds_actual_job_and_lifecycle_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, worker, _repository = _services(tmp_path)
    application.submit(_submission(), actor_id="scheduler")
    events: list[dict[str, object]] = []

    def capture_audit(*args: object, **kwargs: object) -> None:
        context = kwargs["context"]
        events.append(
            {
                "surface": kwargs["surface"],
                "object_type": context.object_type,
                "object_id": context.object_id,
                "action": context.action,
            }
        )

    monkeypatch.setattr(jobs_module, "audit_policy_decision", capture_audit)
    leased = worker.claim(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        entity_id="entity-a",
        worker_id="svc-match-worker",
        occurred_at="2026-08-05T10:00:01Z",
        lease_expires_at="2026-08-05T10:05:01Z",
        policy_context=_context(permissions={"match.run"}),
        required_permission="match.run",
    )
    assert leased is not None
    worker.heartbeat(
        leased,
        occurred_at="2026-08-05T10:00:02Z",
        lease_expires_at="2026-08-05T10:06:01Z",
        policy_context=_context(permissions={"match.run"}),
        required_permission="match.run",
    )
    assert events == [
        {
            "surface": "durable-job.worker.claim",
            "object_type": None,
            "object_id": None,
            "action": "claim",
        },
        {
            "surface": "durable-job.worker.heartbeat",
            "object_type": "durable_job",
            "object_id": "JOB-GOVERNED-WORKER-1",
            "action": "heartbeat",
        },
    ]


@pytest.mark.parametrize(
    "method_name",
    (
        "heartbeat",
        "checkpoint",
        "completed_effects",
        "commit_partition",
        "complete_partition",
        "complete",
        "schedule_retry",
        "fail",
        "pause",
        "cancel",
    ),
)
def test_governed_worker_lifecycle_surface_requires_explicit_policy_context(method_name: str) -> None:
    parameters = inspect.signature(getattr(GovernedDurableJobWorkerService, method_name)).parameters
    assert "policy_context" in parameters
    assert "required_permission" in parameters
