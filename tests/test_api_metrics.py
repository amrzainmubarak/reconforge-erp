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

from reconforge.api import create_api_app, server_metrics
from reconforge.api.routes import metrics as routes
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL
from reconforge.infrastructure.postgres_metrics import install_postgres_metrics_schema
from reconforge.infrastructure.postgres_service_accounts import (
    POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
    PostgresServiceAccountRepository,
)


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    db_path = tmp_path / "metrics-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_server_metrics_routes_bind_tenant_policy_without_workspace(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, headers = _client(tmp_path)
    calls: list[tuple[frozenset[str], str, None]] = []

    def enforce(_request: object, *, permissions: frozenset[str], tenant_id: str, workspace_id: None) -> None:
        calls.append((permissions, tenant_id, workspace_id))

    monkeypatch.setattr(routes, "server_metrics_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "execute_postgres_metrics", lambda _request, _operation: {"bounded": True})
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", enforce)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}

    dashboard = client.get("/api/v1/metrics/dashboard", headers=headers)
    lineage = client.get("/api/v1/metrics/lineage", headers=headers)

    assert dashboard.status_code == 200
    assert lineage.status_code == 200
    assert calls == [
        (frozenset({"metrics.read"}), "tenant-a", None),
        (frozenset({"metrics.read"}), "tenant-a", None),
    ]


def test_server_metrics_executor_uses_configured_identity_factory_and_tenant_boundary(
    monkeypatch: Any,
) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/metrics/dashboard",
            "headers": [(b"x-reconforge-tenant", b"tenant-a")],
        }
    )
    factory = object()
    connection = object()
    observed: list[tuple[object, object, str]] = []

    monkeypatch.setattr(server_metrics, "get_postgres_identity_factory", lambda _request: factory)

    class Boundary:
        def __init__(self, received_factory: object) -> None:
            observed.append((received_factory, connection, "constructed"))

        @contextmanager
        def transaction(self, tenant_id: str):
            observed.append((factory, connection, tenant_id))
            yield connection

    monkeypatch.setattr(server_metrics, "PostgresTenantBoundary", Boundary)

    result = server_metrics.execute_postgres_metrics(
        request,
        lambda repository, tenant_id: (repository.connection, tenant_id),
    )

    assert result == (connection, "tenant-a")
    assert observed == [(factory, connection, "constructed"), (factory, connection, "tenant-a")]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_server_metrics_http_routes_use_postgres_identity_and_rls(
    tmp_path: Path,
) -> None:
    """Exercise both metrics routes through real service authentication and PostgreSQL RLS."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")

    tenant_a = "metrics_api_a_" + uuid4().hex[:8]
    tenant_b = "metrics_api_b_" + uuid4().hex[:8]
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
            install_postgres_metrics_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.tenants, reconforge.identity_permissions, "
                f"reconforge.service_accounts, reconforge.service_account_permissions, "
                f"reconforge.service_account_credentials, reconforge.service_account_events TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT ON reconforge.metric_definitions, reconforge.metric_snapshots TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) "
                "VALUES (%s,'metrics.read','Metrics dashboard and lineage')",
                (tenant_a,),
            )

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            account_repository = PostgresServiceAccountRepository(connection)
            account_repository.create_account(
                tenant_id=tenant_a,
                account_id="svc-metrics-api",
                name="metrics-api",
                display_name="Metrics API",
                permissions=frozenset({"metrics.read"}),
                actor_id="security-admin",
            )
            credential = account_repository.issue_credential(
                tenant_id=tenant_a,
                account_id="svc-metrics-api",
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            headers = {"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {credential.token}"}
            dashboard = client.get("/api/v1/metrics/dashboard", headers=headers)
            assert dashboard.status_code == 200, dashboard.text
            assert dashboard.json()["metrics"] == []

            lineage = client.get("/api/v1/metrics/lineage", headers=headers)
            assert lineage.status_code == 200, lineage.text
            assert {item["metric_key"] for item in lineage.json()["lineage"]} >= {
                "close_completion",
                "match_rate",
            }

            cross_tenant = client.get(
                "/api/v1/metrics/lineage",
                headers={"X-ReconForge-Tenant": tenant_b, "Authorization": f"Bearer {credential.token}"},
            )
            assert cross_tenant.status_code == 401
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events "
                    "DISABLE TRIGGER trg_service_account_events_append_only"
                )
                for table in (
                    "service_account_credentials",
                    "service_account_permissions",
                    "service_account_events",
                    "service_accounts",
                    "identity_permissions",
                ):
                    admin.execute(
                        f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s, %s)",  # nosec B608 - fixed allowlist
                        (tenant_a, tenant_b),
                    )
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events "
                    "ENABLE TRIGGER trg_service_account_events_append_only"
                )
                admin.execute(
                    "DELETE FROM reconforge.tenants WHERE id IN (%s, %s)",
                    (tenant_a, tenant_b),
                )
        finally:
            try:
                with admin.transaction():
                    admin.execute(
                        "ALTER TABLE reconforge.service_account_events "
                        "ENABLE TRIGGER trg_service_account_events_append_only"
                    )
            finally:
                admin.close()
