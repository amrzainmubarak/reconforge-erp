from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import operations
from reconforge.application.jobs import DurableJobApplicationService, JobSubmission
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import DurableJobQueueSnapshot
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL
from reconforge.infrastructure.postgres_jobs import (
    PostgresDurableJobRepository,
    install_postgres_durable_job_schema,
)
from reconforge.infrastructure.postgres_scope_authority import POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL
from reconforge.infrastructure.postgres_service_accounts import (
    POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
    PostgresServiceAccountRepository,
)


def test_local_durable_job_queue_route_is_sanitized_and_authenticated(tmp_path: Path) -> None:
    database_path = tmp_path / "operations.db"
    run_migrations(database_path)
    connection = connect(database_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()

    client = TestClient(create_api_app(database_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.get(
        "/api/v1/ops/durable-jobs/queue",
        params={"tenant_id": "tenant-api", "workspace_id": "workspace-a"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()["queue"]
    assert payload["tenant_id"] == "tenant-api"
    assert payload["workspace_id"] == "workspace-a"
    assert payload["counts"] == {
        "queued": 0,
        "running": 0,
        "paused": 0,
        "retrying": 0,
        "failed": 0,
        "completed": 0,
        "cancelled": 0,
        "leased": 0,
    }
    assert payload["queue_depth"] == 0
    assert "job_id" not in response.text
    assert "input_digest" not in response.text


def test_server_durable_job_queue_route_rechecks_tenant_policy_and_rls_scope(monkeypatch: Any) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/ops/durable-jobs/queue",
            "headers": [(b"x-reconforge-tenant", b"tenant-a")],
        }
    )
    factory = object()
    connection = object()
    policy_calls: list[tuple[str, str]] = []
    boundary_calls: list[tuple[object, str, str | None, str | None]] = []

    monkeypatch.setattr(operations, "server_identity_enabled", lambda _request: True)
    monkeypatch.setattr(operations, "request_tenant_id", lambda _request: "tenant-a")
    monkeypatch.setattr(operations, "get_postgres_identity_factory", lambda _request: factory)
    monkeypatch.setattr(
        operations,
        "enforce_server_tenant_permission",
        lambda _request, *, permission, tenant_id: policy_calls.append((permission, tenant_id)),
    )

    class Boundary:
        def __init__(self, received_factory: object) -> None:
            self.received_factory = received_factory

        @contextmanager
        def transaction(self, tenant_id: str, *, organization_id: str | None, workspace_id: str | None):
            boundary_calls.append((self.received_factory, tenant_id, organization_id, workspace_id))
            yield connection

    class Repository:
        def __init__(self, received_connection: object) -> None:
            assert received_connection is connection

        def queue_snapshot(self, **kwargs: object) -> DurableJobQueueSnapshot:
            assert kwargs == {
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "organization_id": "organization-a",
                "entity_id": "entity-a",
            }
            return DurableJobQueueSnapshot(
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                organization_id="organization-a",
                entity_id="entity-a",
                queued_count=2,
                running_count=1,
                leased_count=1,
            )

    monkeypatch.setattr(operations, "PostgresTenantBoundary", Boundary)
    monkeypatch.setattr(operations, "PostgresDurableJobRepository", Repository)

    result = operations.durable_job_queue(
        request,
        None,
        None,
        tenant_id=None,
        workspace_id="workspace-a",
        organization_id="organization-a",
        entity_id="entity-a",
    )

    assert result["queue"]["tenant_id"] == "tenant-a"
    assert result["queue"]["queue_depth"] == 2
    assert policy_calls == [("ops.read", "tenant-a")]
    assert boundary_calls == [(factory, "tenant-a", "organization-a", "workspace-a")]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_server_durable_job_queue_http_route_is_rls_scoped_and_sanitized(tmp_path: Path) -> None:
    """Exercise the queue-health API through real auth, PostgreSQL, and RLS."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")

    tenant_a = "ops_api_a_" + uuid4().hex[:8]
    tenant_b = "ops_api_b_" + uuid4().hex[:8]
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    try:
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
            pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL)
            admin.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
            install_postgres_durable_job_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.tenants, reconforge.identity_permissions, "
                f"reconforge.service_accounts, reconforge.service_account_permissions, "
                f"reconforge.service_account_credentials, reconforge.service_account_events, "
                f"reconforge.principal_scope_grants, reconforge.durable_jobs, "
                f"reconforge.durable_job_transitions, reconforge.durable_job_leases, "
                f"reconforge.durable_job_lease_events, reconforge.durable_job_partition_effects, "
                f"reconforge.durable_job_scheduler_cursors TO {app_user}"
            )
            admin.execute("GRANT DELETE ON reconforge.durable_job_leases TO " + app_user)
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES (%s,'ops.read','Queue health')",
                (tenant_a,),
            )

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            account_repository = PostgresServiceAccountRepository(connection)
            account_repository.create_account(
                tenant_id=tenant_a,
                account_id="svc-ops-api",
                name="ops-api",
                display_name="Operations API",
                permissions=frozenset({"ops.read"}),
                actor_id="security-admin",
            )
            credential = account_repository.issue_credential(
                tenant_id=tenant_a,
                account_id="svc-ops-api",
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
            DurableJobApplicationService(PostgresDurableJobRepository(connection)).submit(
                JobSubmission(
                    job_id="ops-api-queued-" + uuid4().hex[:8],
                    idempotency_scope="ops-api",
                    idempotency_key="ops-api-queued",
                    tenant_id=tenant_a,
                    workspace_id="workspace-a",
                    entity_id="entity-a",
                    input_digest="1" * 64,
                    config_digest="2" * 64,
                    worker_version="ops-api-test-v1",
                    total_units=1,
                    retry_ceiling=1,
                    created_at="2026-08-09T10:00:00Z",
                ),
                actor_id="ops-api-test",
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            headers = {"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {credential.token}"}
            response = client.get(
                "/api/v1/ops/durable-jobs/queue",
                params={"workspace_id": "workspace-a", "entity_id": "entity-a"},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            payload = response.json()["queue"]
            assert payload["tenant_id"] == tenant_a
            assert payload["workspace_id"] == "workspace-a"
            assert payload["entity_id"] == "entity-a"
            assert payload["counts"]["queued"] == 1
            assert payload["queue_depth"] == 1
            assert "ops-api-queued" not in response.text
            assert "input_digest" not in response.text

            cross_tenant = client.get(
                "/api/v1/ops/durable-jobs/queue",
                params={"tenant_id": tenant_b},
                headers={"X-ReconForge-Tenant": tenant_b, "Authorization": f"Bearer {credential.token}"},
            )
            assert cross_tenant.status_code == 401
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only"
                )
                for table in ("durable_job_transitions", "durable_job_lease_events", "durable_job_partition_effects"):
                    admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER ALL")
                for table in (
                    "service_account_credentials",
                    "service_account_permissions",
                    "service_account_events",
                    "service_accounts",
                    "principal_scope_grants",
                    "durable_job_leases",
                    "durable_job_transitions",
                    "durable_job_lease_events",
                    "durable_job_partition_effects",
                    "durable_jobs",
                    "identity_permissions",
                ):
                    admin.execute(
                        f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s, %s)",  # nosec B608 - fixed allowlist
                        (tenant_a, tenant_b),
                    )
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only"
                )
                admin.execute(
                    "DELETE FROM reconforge.tenants WHERE id IN (%s, %s)",
                    (tenant_a, tenant_b),
                )
        finally:
            try:
                with admin.transaction():
                    admin.execute(
                        "ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only"
                    )
                    for trigger, table in (
                        ("durable_job_transitions_immutable", "durable_job_transitions"),
                        ("durable_job_lease_events_immutable", "durable_job_lease_events"),
                        ("durable_job_partition_effects_immutable", "durable_job_partition_effects"),
                    ):
                        admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER {trigger}")
            finally:
                admin.close()
