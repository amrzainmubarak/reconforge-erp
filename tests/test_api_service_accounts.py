from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations


def test_service_principal_http_me_safe_permission_human_denial_logout_and_tenant_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.auth as auth_routes

    token = "rfa_" + "s" * 64
    revoked = False
    service_user = LocalUser(
        id="svc-worker",
        username="worker",
        display_name="Worker",
        created_at="2026-07-29T00:00:00Z",
    )

    def authenticate(request: Any, supplied: str) -> AuthenticatedServerRequest | None:
        nonlocal revoked
        if request_tenant_id(request) != "tenant-a" or supplied != token or revoked:
            return None
        return AuthenticatedServerRequest(
            user=service_user,
            permissions=frozenset({"db.read", "accounts.review", "reconciliation.prepare"}),
            principal_type="service_account",
            credential_id="sac-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )

    def execute_service(request: Any, operation: Any) -> bool:
        nonlocal revoked

        class Repository:
            def revoke_token(self, *, tenant_id: str, token: str, actor_id: str) -> bool:
                nonlocal revoked
                assert (tenant_id, token, actor_id) == ("tenant-a", "rfa_" + "s" * 64, "svc-worker")
                revoked = True
                return True

        return bool(operation(Repository(), request_tenant_id(request)))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(auth_routes, "execute_postgres_service_account", execute_service)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    run_migrations(tenant_root / "tenant-a.db")
    run_migrations(tenant_root / "tenant-b.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    safe_read = client.get(
        "/api/v1/workflow/transitions",
        headers=headers,
        params={"object_type": "reconciliation"},
    )
    human_review = client.post(
        "/api/v1/accounts/reconciliations/REC-1/review",
        headers=headers,
        json={"reviewer": "worker"},
    )
    dynamic_transition = client.post(
        "/api/v1/workflow/objects/reconciliation/REC-1/transition",
        headers=headers,
        json={"action": "prepare", "reason": "automated"},
    )
    missing_permission = client.get("/api/v1/audit/events", headers=headers)
    cross_tenant = client.get(
        "/api/v1/auth/me",
        headers={"X-ReconForge-Tenant": "tenant-b", "Authorization": f"Bearer {token}"},
    )
    logout = client.post("/api/v1/auth/logout", headers=headers)
    after_logout = client.get("/api/v1/auth/me", headers=headers)

    assert me.status_code == 200
    assert me.json()["principal_type"] == "service_account"
    assert me.json()["roles"] == []
    assert me.json()["permissions"] == ["accounts.review", "db.read", "reconciliation.prepare"]
    assert safe_read.status_code == 200
    assert human_review.status_code == 403
    assert human_review.json()["error"]["code"] == "permission_denied"
    assert dynamic_transition.status_code == 403
    assert dynamic_transition.json()["error"]["code"] == "human_principal_required"
    assert missing_permission.status_code == 403
    assert cross_tenant.status_code == 401
    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    assert after_logout.status_code == 401


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_service_credential_http_auth_policy_tenant_and_logout(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL
    from reconforge.infrastructure.postgres_service_accounts import (
        POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
        PostgresServiceAccountRepository,
    )

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "service_http_a", "service_http_b"
    tables = (
        "service_account_events",
        "service_account_credentials",
        "service_account_permissions",
        "service_accounts",
        "identity_permissions",
    )
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant in (tenant_a, tenant_b):
        run_migrations(root / f"{tenant}.db")
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL)
            admin.execute(
                "ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only"
            )
            for table in tables:
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            admin.execute(
                "ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only"
            )
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES (%s,'db.read','Read')",
                (tenant_a,),
            )
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT,INSERT,UPDATE,DELETE ON "
                    f"reconforge.tenants,reconforge.identity_permissions,"
                    f"reconforge.service_accounts,reconforge.service_account_permissions,"
                    f"reconforge.service_account_credentials,reconforge.service_account_events TO {app_user}"
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresServiceAccountRepository(connection)
            repository.create_account(
                tenant_id=tenant_a,
                account_id="svc-http",
                name="http-worker",
                display_name="HTTP Worker",
                permissions=frozenset({"db.read"}),
                actor_id="security-admin",
            )
            issued = repository.issue_credential(
                tenant_id=tenant_a,
                account_id="svc-http",
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
        client = TestClient(
            create_api_app(
                tmp_path / "unused.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
            )
        )
        headers = {"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {issued.token}"}
        assert client.get("/api/v1/auth/me", headers=headers).json()["principal_type"] == "service_account"
        assert (
            client.get(
                "/api/v1/workflow/transitions",
                headers=headers,
                params={"object_type": "reconciliation"},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/audit/events", headers=headers).status_code == 403
        assert (
            client.post(
                "/api/v1/workflow/objects/reconciliation/REC-1/transition",
                headers=headers,
                json={"action": "prepare", "reason": "automated"},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/auth/me",
                headers={"X-ReconForge-Tenant": tenant_b, "Authorization": f"Bearer {issued.token}"},
            ).status_code
            == 401
        )
        assert client.post("/api/v1/auth/logout", headers=headers).json()["revoked"] is True
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM reconforge.service_account_events WHERE action='REVOKE_CREDENTIAL'"
                ).fetchone()[0]
                == 1
            )
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only"
                )
                for table in tables:
                    admin.execute(
                        f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                        (tenant_a, tenant_b),
                    )
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only"
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        finally:
            admin.close()
