from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_security_center import (
    PostgresSecurityCenterError,
    PostgresSecurityCenterRepository,
)


class _Cursor:
    def __init__(self, row: tuple[int, ...] | None) -> None:
        self.row = row

    def fetchone(self) -> tuple[int, ...] | None:
        return self.row


class _Connection:
    def __init__(self, row: tuple[int, ...] | None) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...]) -> _Cursor:
        self.calls.append((sql, parameters))
        return _Cursor(self.row)


def test_postgres_security_projection_is_one_static_parameterized_count_query() -> None:
    values = [0] * 33
    values[0] = values[1] = 2
    connection = _Connection(tuple(values))
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)

    counts = PostgresSecurityCenterRepository(connection).read_counts(tenant_id="tenant-a", as_of=as_of)

    assert counts.total_users == counts.active_users == 2
    assert counts.disabled_users == 0
    assert len(connection.calls) == 1
    sql, parameters = connection.calls[0]
    assert parameters == ("tenant-a", as_of)
    assert sql.count("%s") == 2
    assert "SELECT *" not in sql.upper()
    assert "password_hash" not in sql
    assert "token_hash" not in sql
    assert "client_ip" not in sql
    assert "user_agent" not in sql
    assert "destination" not in sql
    assert "secret_ref" not in sql
    assert "event_sequence" not in sql


def test_postgres_security_projection_rejects_invalid_inputs_and_shape() -> None:
    repository = PostgresSecurityCenterRepository(_Connection(tuple([0] * 32)))
    with pytest.raises(PostgresSecurityCenterError, match="tenant_id"):
        repository.read_counts(tenant_id="Tenant A", as_of=datetime(2026, 7, 29, tzinfo=UTC))
    with pytest.raises(PostgresSecurityCenterError, match="whole-second"):
        repository.read_counts(tenant_id="tenant-a", as_of=datetime(2026, 7, 29, microsecond=1, tzinfo=UTC))
    with pytest.raises(PostgresSecurityCenterError, match="unavailable"):
        repository.read_counts(tenant_id="tenant-a", as_of=datetime(2026, 7, 29, tzinfo=UTC))

    invalid = [0] * 33
    invalid[0] = -1
    with pytest.raises(PostgresSecurityCenterError, match="invalid aggregate"):
        PostgresSecurityCenterRepository(_Connection(tuple(invalid))).read_counts(
            tenant_id="tenant-a", as_of=datetime(2026, 7, 29, tzinfo=UTC)
        )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_security_center_http_is_tenant_scoped_redacted_and_human_only(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    suffix = uuid4().hex[:10]
    tenant_a = f"security_center_a_{suffix}"
    tenant_b = f"security_center_b_{suffix}"
    password = "Synthetic-security-center-password-123!"
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant in (tenant_a, tenant_b):
        run_migrations(root / f"{tenant}.db")
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant, username in ((tenant_a, "security-admin"), (tenant_b, "sibling-admin")):
            with PostgresTenantBoundary(admin_factory).transaction(tenant) as connection:
                identity = PostgresIdentityRepository(connection)
                identity.create_permission(
                    tenant_id=tenant,
                    permission_name="security.center.read",
                    description="Read count-only security overview",
                )
                identity.create_role(tenant_id=tenant, role_name="security-reviewer")
                identity.grant_permission(
                    tenant_id=tenant,
                    role_name="security-reviewer",
                    permission_name="security.center.read",
                )
                identity.create_user(
                    tenant_id=tenant,
                    user_id=f"user-{tenant}",
                    username=username,
                    display_name="Synthetic Security Reviewer",
                    password=password,
                    role_name="security-reviewer",
                )
        with PostgresTenantBoundary(admin_factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_user(
                tenant_id=tenant_a,
                user_id=f"disabled-{suffix}",
                username=f"disabled-{suffix}",
                display_name="Disabled Synthetic User",
                password=password,
                role_name="security-reviewer",
            )
            connection.execute(
                """UPDATE reconforge.identity_users
                   SET disabled=TRUE,disabled_at=now(),disabled_by=%s,lifecycle_version=lifecycle_version+1
                   WHERE tenant_id=%s AND id=%s""",
                (f"user-{tenant_a}", tenant_a, f"disabled-{suffix}"),
            )
            connection.execute(
                """INSERT INTO reconforge.service_accounts
                   (tenant_id,id,name,display_name,enabled,version,max_credential_ttl_seconds,created_by)
                   VALUES (%s,%s,%s,'Hostile SQL account',TRUE,1,3600,%s)""",
                (tenant_a, f"svc-{suffix}", f"svc-{suffix}", f"user-{tenant_a}"),
            )
        with pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
            admin.execute(
                """INSERT INTO reconforge.service_account_permissions
                   (tenant_id,service_account_id,permission_name,granted_by)
                   VALUES (%s,%s,'security.center.read',%s)""",
                (tenant_a, f"svc-{suffix}", f"user-{tenant_a}"),
            )

        client = TestClient(
            create_api_app(
                tmp_path / "control.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
            )
        )
        tenant_headers = {"X-ReconForge-Tenant": tenant_a}
        login = client.post(
            "/api/v1/auth/login",
            headers=tenant_headers,
            json={"username": "security-admin", "password": password},
        )
        assert login.status_code == 200, login.text
        headers = {**tenant_headers, "Authorization": f"Bearer {login.json()['access_token']}"}
        before_step_up = client.get("/api/v1/admin/security/overview", headers=headers)
        assert before_step_up.status_code == 403
        assert before_step_up.json()["error"]["code"] == "step_up_required"
        step_up = client.post("/api/v1/auth/step-up", headers=headers, json={"password": password})
        assert step_up.status_code == 200, step_up.text
        response = client.get("/api/v1/admin/security/overview", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["identity"] == {
            "total_users": 2,
            "active_users": 1,
            "disabled_users": 1,
            "locked_users": 0,
            "active_users_without_roles": 0,
            "roles": 1,
            "permissions": 1,
            "role_permission_bindings": 1,
        }
        assert payload["claim_boundary"] == "operational_snapshot_not_security_assurance"
        assert payload["audit"]["chain_verification"] == "not_evaluated_use_audit_verify_endpoint"
        assert set(payload["audit"]) == {"audit_events", "chain_verification"}
        for secret in (
            "security-admin",
            "sibling-admin",
            f"disabled-{suffix}",
            password,
            tenant_a,
            tenant_b,
        ):
            assert secret not in response.text
    finally:
        admin.close()
