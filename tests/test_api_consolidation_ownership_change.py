from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import consolidation_ownership_change as routes
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from tests.test_consolidation_ownership_changes import _request


def _body() -> dict[str, object]:
    payload = _request().to_dict()
    payload.pop("prepared_by", None)
    return payload


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    db_path = tmp_path / "ownership-change-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_ownership_change_api_is_server_profile_only_and_authenticated(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}

    unauthenticated = client.post("/api/v1/consolidation-ownership-change", json=_body())
    assert unauthenticated.status_code == 401
    unavailable = client.post("/api/v1/consolidation-ownership-change", headers=headers, json=_body())
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "consolidation_ownership_change_unavailable"


def test_ownership_change_api_rebuilds_typed_request_and_binds_authenticated_actor(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, headers = _client(tmp_path)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}
    captured: dict[str, object] = {}

    class Repository:
        def persist(self, request: object, result: object, **_: object) -> dict[str, object]:
            captured["request"] = request
            captured["result"] = result
            return {
                "id": "ownchg-" + "a" * 32,
                "posted": False,
                "result_digest": result.result_digest,  # type: ignore[union-attr]
            }

        def get(self, artifact_id: str, **_: object) -> dict[str, object]:
            return {"id": artifact_id, "posted": False}

    repository = Repository()

    def execute(_request: object, operation: object) -> object:
        return operation(repository, "tenant-a")  # type: ignore[operator]

    monkeypatch.setattr(routes, "server_ownership_change_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "execute_postgres_ownership_change", execute)

    actor_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    created = client.post("/api/v1/consolidation-ownership-change", headers=headers, json=_body())
    assert created.status_code == 200, created.text
    assert created.json()["artifact"]["posted"] is False
    assert captured["request"].prepared_by == actor_id  # type: ignore[union-attr]
    assert captured["request"].approved_by == "reviewer"  # type: ignore[union-attr]

    loaded = client.get(
        "/api/v1/consolidation-ownership-change/ownchg-" + "a" * 32,
        headers=headers,
    )
    assert loaded.status_code == 200
    assert loaded.json()["artifact"]["posted"] is False

    invalid = _body()
    invalid["unexpected"] = True
    rejected = client.post("/api/v1/consolidation-ownership-change", headers=headers, json=invalid)
    assert rejected.status_code == 422

    self_approval = _body()
    self_approval["approved_by"] = actor_id
    rejected_self_approval = client.post(
        "/api/v1/consolidation-ownership-change", headers=headers, json=self_approval
    )
    assert rejected_self_approval.status_code == 400
    assert rejected_self_approval.json()["error"]["code"] == "consolidation_ownership_change_request_invalid"


def test_ownership_change_server_routes_re_evaluate_tenant_policy_without_workspace(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, headers = _client(tmp_path)
    captured: list[tuple[frozenset[str], str, None, object]] = []

    def enforce(
        _request: object,
        *,
        permissions: frozenset[str],
        tenant_id: str,
        workspace_id: None,
        amount: object = None,
    ) -> None:
        captured.append((permissions, tenant_id, workspace_id, amount))

    monkeypatch.setattr(routes, "server_ownership_change_enabled", lambda _request: True)
    monkeypatch.setattr(
        routes,
        "execute_postgres_ownership_change",
        lambda _request, _operation: {"id": "ownchg-" + "a" * 32, "posted": False},
    )
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", enforce)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}

    created = client.post("/api/v1/consolidation-ownership-change", headers=headers, json=_body())
    assert created.status_code == 200
    assert captured == [(frozenset({"finance_core.manage"}), "tenant-a", None, Decimal("220.00"))]

    loaded = client.get(
        "/api/v1/consolidation-ownership-change/ownchg-" + "a" * 32,
        headers=headers,
    )
    assert loaded.status_code == 200
    assert captured[-1] == (frozenset({"finance_core.read", "finance_core.manage"}), "tenant-a", None, None)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_ownership_change_api_is_rls_scoped_and_non_posting(tmp_path: Path) -> None:
    """Exercise the real authenticated server route with a non-superuser role."""

    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_consolidation_ownership_change import (
        POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL,
    )
    from reconforge.infrastructure.postgres_domain import POSTGRES_DOMAIN_SCHEMA_SQL
    from reconforge.infrastructure.postgres_emergency_access import POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL
    from reconforge.infrastructure.postgres_identity import (
        POSTGRES_IDENTITY_SCHEMA_SQL,
        PostgresIdentityRepository,
    )
    from reconforge.infrastructure.postgres_privileged_sessions import POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    from reconforge.infrastructure.postgres_scope_authority import POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    token = uuid4().hex[:8]
    tenant_a = f"ownchg_api_a_{token}"
    tenant_b = f"ownchg_api_b_{token}"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = None
    try:
        admin = admin_factory.connect()
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_DOMAIN_SCHEMA_SQL)
            admin.execute(POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL)
            admin.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
            admin.execute(POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                f"reconforge.identity_sessions, reconforge.identity_step_up_assertions, "
                f"reconforge.emergency_access_requests, reconforge.emergency_access_permissions, "
                f"reconforge.emergency_access_events, "
                f"reconforge.domain_workspaces, "
                f"reconforge.principal_scope_grants, reconforge.consolidation_ownership_change_artifacts, "
                f"reconforge.domain_audit_ledger_state, reconforge.domain_audit_events "
                f"TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )

        role = app_factory.connect()
        try:
            role_flags = role.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
        finally:
            role.close()
        if role_flags is None or bool(role_flags[0]) or bool(role_flags[1]):
            pytest.skip("live ownership-change API requires a non-superuser, non-BYPASSRLS role")

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, "workspace-a", "Ownership API workspace"),
            )
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="Admin")
            identity.create_permission(tenant_id=tenant_a, permission_name="finance_core.read")
            identity.create_permission(tenant_id=tenant_a, permission_name="finance_core.manage")
            identity.grant_permission(
                tenant_id=tenant_a, role_name="admin", permission_name="finance_core.read"
            )
            identity.grant_permission(
                tenant_id=tenant_a, role_name="admin", permission_name="finance_core.manage"
            )
            identity.create_user(
                tenant_id=tenant_a,
                user_id="api-preparer",
                username="preparer",
                password="Strong-password-123",
                role_name="admin",
            )
            identity.create_user(
                tenant_id=tenant_a,
                user_id="api-reviewer",
                username="reviewer",
                password="Strong-password-123",
                role_name="admin",
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            base_headers = {"X-ReconForge-Tenant": tenant_a}
            login = client.post(
                "/api/v1/auth/login",
                headers=base_headers,
                json={"username": "preparer", "password": "Strong-password-123"},
            )
            assert login.status_code == 200, login.text
            headers = {
                **base_headers,
                "Authorization": f"Bearer {login.json()['access_token']}",
                "X-ReconForge-Workspace": "workspace-a",
            }
            step_up = client.post(
                "/api/v1/auth/step-up",
                headers=headers,
                json={"password": "Strong-password-123"},
            )
            assert step_up.status_code == 200, step_up.text
            payload = _request().to_dict()
            payload.pop("prepared_by", None)
            payload["approved_by"] = "api-reviewer"
            created = client.post(
                "/api/v1/consolidation-ownership-change", headers=headers, json=payload
            )
            assert created.status_code == 200, created.text
            assert created.json()["artifact"]["posted"] is False
            artifact_id = created.json()["artifact"]["id"]
            loaded = client.get(
                f"/api/v1/consolidation-ownership-change/{artifact_id}", headers=headers
            )
            assert loaded.status_code == 200, loaded.text
            assert loaded.json()["artifact"]["result_payload"]["posted"] is False
            cross_tenant = client.get(
                f"/api/v1/consolidation-ownership-change/{artifact_id}",
                headers={**headers, "X-ReconForge-Tenant": tenant_b},
            )
            assert cross_tenant.status_code == 401
    finally:
        if admin is not None:
            try:
                with admin.transaction():
                    admin.execute(
                        "ALTER TABLE reconforge.consolidation_ownership_change_artifacts "
                        "DISABLE TRIGGER consolidation_ownership_change_artifact_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.domain_audit_events "
                        "DISABLE TRIGGER domain_audit_events_immutable"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.identity_step_up_assertions "
                        "DISABLE TRIGGER identity_step_up_assertions_append_only"
                    )
                    admin.execute(
                        "DELETE FROM reconforge.consolidation_ownership_change_artifacts "
                        "WHERE tenant_id IN (%s,%s)",
                        (tenant_a, tenant_b),
                    )
                    admin.execute(
                        "DELETE FROM reconforge.domain_audit_events WHERE tenant_id IN (%s,%s)",
                        (tenant_a, tenant_b),
                    )
                    admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
                    admin.execute(
                        "ALTER TABLE reconforge.domain_audit_events "
                        "ENABLE TRIGGER domain_audit_events_immutable"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.identity_step_up_assertions "
                        "ENABLE TRIGGER identity_step_up_assertions_append_only"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.consolidation_ownership_change_artifacts "
                        "ENABLE TRIGGER consolidation_ownership_change_artifact_guard"
                    )
            finally:
                admin.close()
