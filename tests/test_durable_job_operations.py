from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import durable_job_operations as routes
from reconforge.application.job_operations import JobOperationsScope, JobOperationsService
from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobVersionConflictError,
    DurableJobWorkerService,
    GovernedDurableJobApplicationService,
    JobAuthorizationError,
    JobSubmission,
)
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.db.migration_56_job_operations import SQLITE_JOB_OPERATIONS_UPGRADE_SQL
from reconforge.domain.jobs import JobStatus
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository, SQLiteJobConflictError
from reconforge.platform.common import ServerPrincipal


def submission(job_id: str = "job-a", **changes: object) -> JobSubmission:
    values: dict[str, object] = dict(job_id=job_id, idempotency_scope="imports", idempotency_key=job_id,
                                    tenant_id="local", workspace_id="workspace-a", entity_id="entity-a",
                                    input_digest="1" * 64, config_digest="2" * 64, worker_version="worker-v1",
                                    total_units=2, retry_ceiling=1, created_at="2026-08-02T10:00:00Z")
    values.update(changes)
    return JobSubmission(**values)  # type: ignore[arg-type]


def context(**changes: object) -> PolicyEvaluationContext:
    base = PolicyEvaluationContext(user_id="operator", username="operator", user_permissions={"ops.read", "jobs.manage"},
                                   tenant_id="local", workspace_id="workspace-a", entity_id="entity-a",
                                   authorized_tenant_ids=frozenset({"local"}),
                                   authorized_workspace_ids=frozenset({"workspace-a"}),
                                   authorized_entity_ids=frozenset({"entity-a"}))
    return replace(base, **changes)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.db"
    run_migrations(path)
    with connect(path) as connection:
        connection.executescript(SQLITE_JOB_OPERATIONS_UPGRADE_SQL)
        LocalAuthService(connection).init_admin(username="admin", password="Synthetic-only-123")
    return path


def test_governed_cancel_binds_persisted_hierarchy(database: Path) -> None:
    connection = connect(database)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    application.submit(submission(), actor_id="operator")
    service = GovernedDurableJobApplicationService(application)
    for changed in (dict(workspace_id="workspace-b", authorized_workspace_ids=frozenset({"workspace-b"})),
                    dict(entity_id="entity-b", authorized_entity_ids=frozenset({"entity-b"})),
                    dict(organization_id="organization-b", authorized_organization_ids=frozenset({"organization-b"}))):
        selected = context(**changed)
        with pytest.raises(JobAuthorizationError, match="persisted job scope"):
            service.cancel(tenant_id="local", workspace_id=str(selected.workspace_id),
                           organization_id=selected.organization_id, entity_id=selected.entity_id, job_id="job-a",
                           actor_id="operator", occurred_at="2026-08-02T10:01:00Z", policy_context=selected,
                           required_permission="jobs.manage", expected_version=1)
    assert repository.get(tenant_id="local", job_id="job-a").version == 1
    assert len(repository.list_transitions(tenant_id="local", job_id="job-a")) == 1
    connection.close()


def test_operator_page_is_keyset_scoped_filtered_and_closed(database: Path) -> None:
    connection = connect(database)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    for identifier in ("job-a", "job-b", "job-c"):
        application.submit(submission(identifier), actor_id="operator")
    application.submit(submission("job-sibling", entity_id="entity-b"), actor_id="operator")
    application.submit(submission("job-tenant", tenant_id="other"), actor_id="operator")
    application.cancel(tenant_id="local", job_id="job-a", actor_id="operator", occurred_at="2026-08-02T10:01:00Z")
    reads = JobOperationsService(repository)
    scope = JobOperationsScope("local", "workspace-a", "entity-a")
    first = reads.page(scope, context(), limit=1)
    assert first["next_after_id"] == "job-a"
    second = reads.page(scope, context(), limit=2, after_id="job-a")
    assert [record["id"] for record in second["records"]] == ["job-b", "job-c"]
    assert second["next_after_id"] == ""
    filtered = reads.page(scope, context(), status=JobStatus.CANCELLED)
    assert [record["id"] for record in filtered["records"]] == ["job-a"]
    assert all("idempotency_key" not in record and "input_digest" not in record and "output_manifest_reference" not in record for record in filtered["records"])
    with pytest.raises(JobAuthorizationError):
        reads.page(scope, context(user_permissions={"jobs.manage"}))
    connection.close()


def test_versioned_cancel_replay_and_running_fence(database: Path) -> None:
    connection = connect(database)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    application.submit(submission(), actor_id="operator")
    first = application.cancel(tenant_id="local", job_id="job-a", actor_id="operator", occurred_at="2026-08-02T10:01:00Z", expected_version=1)
    assert application.cancel(tenant_id="local", job_id="job-a", actor_id="operator", occurred_at="2026-08-02T10:02:00Z", expected_version=1) == first
    assert len(repository.list_transitions(tenant_id="local", job_id="job-a")) == 2
    with pytest.raises(DurableJobVersionConflictError):
        application.cancel(tenant_id="local", job_id="job-a", actor_id="another", occurred_at="2026-08-02T10:02:00Z", expected_version=1)
    application.submit(submission("job-running"), actor_id="operator")
    worker = DurableJobWorkerService(repository)
    leased = worker.claim(tenant_id="local", worker_id="worker-a", occurred_at="2026-08-02T10:03:00Z", lease_expires_at="2026-08-02T10:10:00Z")
    assert leased is not None
    with pytest.raises(SQLiteJobConflictError):
        application.cancel(tenant_id="local", job_id="job-running", actor_id="operator", occurred_at="2026-08-02T10:04:00Z", expected_version=leased.job.version)
    assert repository.get(tenant_id="local", job_id="job-running").status is JobStatus.RUNNING
    worker.fail(leased, occurred_at="2026-08-02T10:05:00Z", safe_error_code="SYNTHETIC_FAILURE")
    failed = repository.get(tenant_id="local", job_id="job-running")
    requeued = application.requeue(tenant_id="local", job_id=failed.id, actor_id="operator", occurred_at="2026-08-02T10:06:00Z", expected_version=failed.version)
    assert application.requeue(tenant_id="local", job_id=failed.id, actor_id="operator", occurred_at="2026-08-02T10:07:00Z", expected_version=failed.version) == requeued
    connection.close()


def test_concurrent_cancellations_append_one_effect(database: Path) -> None:
    connection = connect(database)
    DurableJobApplicationService(SQLiteDurableJobRepository(connection)).submit(submission(), actor_id="operator")
    connection.close()
    def act() -> int:
        db = connect(database)
        try:
            service = DurableJobApplicationService(SQLiteDurableJobRepository(db))
            try:
                return service.cancel(tenant_id="local", job_id="job-a", actor_id="operator", occurred_at="2026-08-02T10:01:00Z", expected_version=1).version
            except SQLiteJobConflictError:
                return 0
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(lambda _: act(), range(6)))
    assert 2 in outcomes and set(outcomes) <= {0, 2}
    connection = connect(database)
    assert len(SQLiteDurableJobRepository(connection).list_transitions(tenant_id="local", job_id="job-a")) == 2
    connection.close()


def client_for(database: Path) -> tuple[TestClient, dict[str, str]]:
    app = create_api_app(database)
    # Root registration is verified independently by the integrated gate.
    if "/api/v1/ops/durable-jobs" not in app.openapi()["paths"]:
        app.include_router(routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Synthetic-only-123"})
    return client, {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_api_real_lifecycle_scope_and_retry(database: Path) -> None:
    connection = connect(database)
    DurableJobApplicationService(SQLiteDurableJobRepository(connection)).submit(submission(), actor_id="operator")
    connection.close()
    client, headers = client_for(database)
    scope = {"workspace_id": "workspace-a", "entity_id": "entity-a"}
    page = client.get("/api/v1/ops/durable-jobs", params=scope, headers=headers)
    assert page.status_code == 200 and page.json()["records"][0]["id"] == "job-a"
    foreign = client.get("/api/v1/ops/durable-jobs/job-a", params={**scope, "entity_id": "entity-b"}, headers=headers)
    assert foreign.status_code == 404
    foreign_write = client.post("/api/v1/ops/durable-jobs/job-a/cancel", params={**scope, "workspace_id": "workspace-b"}, headers=headers, json={"expected_version": 1})
    assert foreign_write.status_code == 404
    cancelled = client.post("/api/v1/ops/durable-jobs/job-a/cancel", params=scope, headers=headers, json={"expected_version": 1})
    assert cancelled.status_code == 200 and cancelled.json()["job"]["version"] == 2
    replay = client.post("/api/v1/ops/durable-jobs/job-a/cancel", params=scope, headers=headers, json={"expected_version": 1})
    assert replay.json() == cancelled.json()
    history = client.get("/api/v1/ops/durable-jobs/job-a", params=scope, headers=headers).json()
    assert [event["reason_code"] for event in history["transitions"]] == ["CREATED", "CANCELLED"]
    assert "idempotency" not in str(history)
    assert client.post("/api/v1/ops/durable-jobs/job-a/cancel", params=scope, headers=headers, json={"expected_version": True}).status_code == 422


def test_api_read_permission_cannot_mutate(database: Path) -> None:
    connection = connect(database)
    DurableJobApplicationService(SQLiteDurableJobRepository(connection)).submit(submission(), actor_id="operator")
    connection.execute("DELETE FROM role_permissions WHERE permission_name='jobs.manage'")
    connection.commit()
    connection.close()
    client, headers = client_for(database)
    scope = {"workspace_id": "workspace-a", "entity_id": "entity-a"}
    assert client.get("/api/v1/ops/durable-jobs", params=scope, headers=headers).status_code == 200
    assert client.post("/api/v1/ops/durable-jobs/job-a/cancel", params=scope, headers=headers, json={"expected_version": 1}).status_code == 403
    assert client.get("/api/v1/ops/durable-jobs", params=scope).status_code == 401


def test_server_scope_requires_grants_and_explicit_coherence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "server_identity_enabled", lambda _request: True)
    request = Request({"type": "http", "headers": [(b"x-reconforge-tenant", b"tenant-a"),
                      (b"x-reconforge-workspace", b"workspace-a"), (b"x-reconforge-organization", b"organization-a"),
                      (b"x-reconforge-legal-entity", b"entity-a")], "query_string": b""})
    request.state.server_principal = ServerPrincipal(user=LocalUser(id="operator", username="operator", display_name="Operator"),
                                                     permissions=frozenset({"ops.read"}), authorized_tenant_ids=frozenset({"tenant-a"}),
                                                     authorized_workspace_ids=frozenset({"workspace-a"}), authorized_organization_ids=frozenset({"organization-a"}),
                                                     authorized_legal_entity_ids=frozenset({"entity-a"}))
    scope = routes.selected_job_scope(request, "local", "", "", "")
    assert scope == JobOperationsScope("tenant-a", "workspace-a", "entity-a", "organization-a")
    request = Request({**request.scope, "query_string": b"entity_id=entity-b"})
    with pytest.raises(routes.APIError) as error:
        routes.selected_job_scope(request, "tenant-a", "workspace-a", "organization-a", "entity-b")
    assert error.value.status_code == 403
    request = Request({**request.scope, "query_string": b""})
    request.state.server_principal = replace(request.state.server_principal, authorized_workspace_ids=frozenset({"workspace-other"}))
    with pytest.raises(routes.APIError) as denied:
        routes.selected_job_scope(request, "local", "", "", "")
    assert denied.value.code == "workspace_scope_denied"
