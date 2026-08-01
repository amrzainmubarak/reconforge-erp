from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_http_emergency_request_approval_activation_use_end_and_review(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_emergency_access import POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL, PostgresIdentityRepository
    from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
    from reconforge.infrastructure.postgres_privileged_sessions import POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "emergency_http_a", "emergency_http_b"
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant in (tenant_a, tenant_b):
        run_migrations(root / f"{tenant}.db")
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL)
            admin.execute(POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            for trigger, table in (
                ("emergency_access_events_append_only", "emergency_access_events"),
                ("emergency_access_permissions_immutable", "emergency_access_permissions"),
                ("emergency_access_requests_no_delete", "emergency_access_requests"),
                ("identity_step_up_assertions_append_only", "identity_step_up_assertions"),
                ("principal_scope_grants_guard", "principal_scope_grants"),
            ):
                admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER {trigger}")
            for table in (
                "principal_scope_grants",
                "emergency_access_events",
                "emergency_access_permissions",
                "emergency_access_requests",
                "identity_step_up_assertions",
                "identity_role_permissions",
                "identity_users",
                "identity_permissions",
                "identity_roles",
            ):
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            for trigger, table in (
                ("emergency_access_events_append_only", "emergency_access_events"),
                ("emergency_access_permissions_immutable", "emergency_access_permissions"),
                ("emergency_access_requests_no_delete", "emergency_access_requests"),
                ("identity_step_up_assertions_append_only", "identity_step_up_assertions"),
                ("principal_scope_grants_guard", "principal_scope_grants"),
            ):
                admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER {trigger}")
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
                admin.execute(f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            for role in ("requester", "approver", "reviewer"):
                identity.create_role(tenant_id=tenant_a, role_name=role)
            for permission in (
                "finance_core.validate",
                "security.emergency.approve",
                "security.emergency.review",
            ):
                identity.create_permission(tenant_id=tenant_a, permission_name=permission)
            identity.grant_permission(
                tenant_id=tenant_a, role_name="approver", permission_name="security.emergency.approve"
            )
            identity.grant_permission(
                tenant_id=tenant_a, role_name="reviewer", permission_name="security.emergency.review"
            )
            for name in ("requester", "approver", "reviewer"):
                identity.create_user(
                    tenant_id=tenant_a,
                    user_id=f"http-{name}",
                    username=name,
                    password="Strong-password-123",
                    role_name=name,
                )
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                (tenant_a, "emergency-workspace", "Emergency test workspace"),
            )
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=tenant_a,
                grant_id="emergency-http-requester-workspace",
                principal_type="user",
                principal_id="http-requester",
                scope_type="workspace",
                scope_id="emergency-workspace",
                actor_id="http-approver",
            )
        client = TestClient(
            create_api_app(
                tmp_path / "unused.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
            )
        )

        def authenticated(name: str) -> dict[str, str]:
            tenant_headers = {
                "X-ReconForge-Tenant": tenant_a,
                "X-ReconForge-Workspace": "emergency-workspace",
            }
            login = client.post(
                "/api/v1/auth/login",
                headers=tenant_headers,
                json={"username": name, "password": "Strong-password-123"},
            )
            assert login.status_code == 200
            headers = {**tenant_headers, "Authorization": f"Bearer {login.json()['access_token']}"}
            stepped = client.post(
                "/api/v1/auth/step-up",
                headers=headers,
                json={"password": "Strong-password-123"},
            )
            assert stepped.status_code == 200
            return headers

        requester = authenticated("requester")
        approver = authenticated("approver")
        reviewer = authenticated("reviewer")
        before = client.get("/api/v1/finance-core/summary", headers=requester)
        requested = client.post(
            "/api/v1/auth/emergency-access/requests",
            headers=requester,
            json={
                "permissions": ["finance_core.validate"],
                "reason": "Restore a blocked synthetic validation during incident recovery",
                "incident_reference": "INC-HTTP-001",
                "requested_minutes": 15,
            },
        )
        assert before.status_code == 403
        assert requested.status_code == 200, requested.text
        request_record = requested.json()["request"]
        access_id = request_record["id"]
        self_approve = client.post(
            f"/api/v1/auth/emergency-access/requests/{access_id}/approve",
            headers=requester,
            json={"expected_version": request_record["version"]},
        )
        approved = client.post(
            f"/api/v1/auth/emergency-access/requests/{access_id}/approve",
            headers=approver,
            json={"expected_version": request_record["version"]},
        )
        assert self_approve.status_code == 403
        assert approved.status_code == 200, approved.text
        activated = client.post(
            f"/api/v1/auth/emergency-access/requests/{access_id}/activate",
            headers=requester,
            json={"expected_version": approved.json()["request"]["version"]},
        )
        assert activated.status_code == 200, activated.text
        elevated = client.get("/api/v1/finance-core/summary", headers=requester)
        assert elevated.status_code == 200, elevated.text
        ended = client.post(
            f"/api/v1/auth/emergency-access/requests/{access_id}/end",
            headers=requester,
            json={
                "expected_version": activated.json()["request"]["version"],
                "note": "Synthetic emergency validation completed safely",
            },
        )
        assert ended.status_code == 200, ended.text
        after = client.get("/api/v1/finance-core/summary", headers=requester)
        assert after.status_code == 403
        self_review = client.post(
            f"/api/v1/auth/emergency-access/requests/{access_id}/review",
            headers=requester,
            json={
                "expected_version": ended.json()["request"]["version"],
                "outcome": "Confirmed",
                "note": "Requester must not review their own emergency operation",
            },
        )
        reviewed = client.post(
            f"/api/v1/auth/emergency-access/requests/{access_id}/review",
            headers=reviewer,
            json={
                "expected_version": ended.json()["request"]["version"],
                "outcome": "Confirmed",
                "note": "Independent reviewer confirmed the bounded synthetic operation",
            },
        )
        assert self_review.status_code == 403
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["request"]["status"] == "Reviewed"
        listed = client.get("/api/v1/auth/emergency-access/requests", headers=approver)
        cross_tenant = client.get(
            "/api/v1/auth/emergency-access/requests",
            headers={**requester, "X-ReconForge-Tenant": tenant_b},
        )
        assert listed.status_code == 200 and len(listed.json()["requests"]) == 1
        assert cross_tenant.status_code == 401
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            use_rows = connection.execute(
                "SELECT permission_name,surface FROM reconforge.emergency_access_events WHERE action='used'"
            ).fetchall()
            assert [tuple(row) for row in use_rows] == [
                ("finance_core.validate", "GET /api/v1/finance-core/summary")
            ]
    finally:
        admin.close()
