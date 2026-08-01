from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.access_administration import AccessAdministrationError
from reconforge.application.identity_administration import IdentityAdministrationError
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_access_administration import PostgresAccessAdministrationRepository
from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL, PostgresIdentityRepository
from reconforge.infrastructure.postgres_identity_administration import PostgresIdentityAdministrationRepository


def test_access_lifecycle_schema_is_closed_versioned_and_forced_rls() -> None:
    assert "identity_roles_lifecycle_version_positive" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "identity_roles_retirement_state_consistent" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "identity_user_roles_state_consistent" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "identity_role_permissions_state_consistent" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "'role_retired'" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert POSTGRES_IDENTITY_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 6


def test_access_repository_uses_parameterized_bounded_static_sql() -> None:
    source = Path("reconforge/infrastructure/postgres_access_administration.py").read_text(encoding="utf-8")
    assert "LIMIT 513" in source
    assert "LIMIT %s" in source
    assert "pg_advisory_xact_lock" in source
    assert "ANY(%s)" in source
    assert "EXECUTE format" not in source
    assert "execute(f" not in source
    assert "roles.manage" in source
    assert "access_last_manager_forbidden" in source


def test_access_lifecycle_docs_and_migration_are_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/adr/0196-authoritative-postgres-access-policy-lifecycle.md" in manifest
    assert "include docs/operations/access-administration.md" in manifest
    assert "recursive-include alembic/versions *.py" in manifest


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_access_admin_is_atomic_tenant_isolated_and_invalidates_authority(
    tmp_path: Path, monkeypatch: Any
) -> None:
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"access_admin_a_{suffix}"
    tenant_b = f"access_admin_b_{suffix}"
    tenant_c = f"access_admin_c_{suffix}"
    actor_id = f"actor-{suffix}"
    backup_id = f"backup-{suffix}"
    target_id = f"target-{suffix}"
    sibling_id = f"sibling-{suffix}"
    lone_id = f"lone-{suffix}"
    identity_admin_id = f"identity-admin-{suffix}"
    password = "Synthetic-access-admin-password-123!"
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant in (tenant_a, tenant_b, tenant_c):
        run_migrations(root / f"{tenant}.db")

    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b, tenant_c, tenant_c),
            )

        def provision(tenant: str, users: tuple[tuple[str, str, str], ...]) -> None:
            with PostgresTenantBoundary(admin_factory).transaction(tenant) as connection:
                identity = PostgresIdentityRepository(connection)
                for permission in ("roles.manage", "audit.read", "reports.read"):
                    identity.create_permission(tenant_id=tenant, permission_name=permission)
                identity.create_role(tenant_id=tenant, role_name="administrator")
                identity.create_role(tenant_id=tenant, role_name="reviewer")
                identity.grant_permission(
                    tenant_id=tenant, role_name="administrator", permission_name="roles.manage"
                )
                identity.grant_permission(tenant_id=tenant, role_name="reviewer", permission_name="audit.read")
                for user_id, username, role in users:
                    identity.create_user(
                        tenant_id=tenant,
                        user_id=user_id,
                        username=username,
                        password=password,
                        role_name=role,
                        display_name=f"Synthetic {username}",
                        email=f"{username}@sensitive.invalid",
                    )

        provision(
            tenant_a,
            (
                (actor_id, f"actor-{suffix}", "administrator"),
                (backup_id, f"backup-{suffix}", "administrator"),
                (target_id, f"target-{suffix}", "reviewer"),
            ),
        )
        provision(tenant_b, ((sibling_id, f"sibling-{suffix}", "administrator"),))
        provision(
            tenant_c,
            (
                (lone_id, f"lone-{suffix}", "administrator"),
                (identity_admin_id, f"identity-admin-{suffix}", "reviewer"),
            ),
        )
        with PostgresTenantBoundary(admin_factory).transaction(tenant_c) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_permission(tenant_id=tenant_c, permission_name="users.manage")
            identity.grant_permission(
                tenant_id=tenant_c, role_name="reviewer", permission_name="users.manage"
            )

        client = TestClient(
            create_api_app(
                tmp_path / "control.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
                cursor_signing_key=b"live-e192-cursor-signing-key-32-bytes",
            )
        )

        def login(tenant: str, username: str) -> tuple[str, dict[str, str]]:
            response = client.post(
                "/api/v1/auth/login",
                headers={"X-ReconForge-Tenant": tenant},
                json={"username": username, "password": password},
            )
            assert response.status_code == 200, response.text
            token = str(response.json()["access_token"])
            return token, {
                "X-ReconForge-Tenant": tenant,
                "Authorization": f"Bearer {token}",
            }

        actor_token, actor_headers = login(tenant_a, f"actor-{suffix}")
        target_token, _target_headers = login(tenant_a, f"target-{suffix}")
        sibling_token, sibling_headers = login(tenant_b, f"sibling-{suffix}")
        denied = client.get("/api/v1/admin/access/roles", headers=actor_headers)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "step_up_required"
        step_up = client.post("/api/v1/auth/step-up", headers=actor_headers, json={"password": password})
        assert step_up.status_code == 200, step_up.text
        sibling_step_up = client.post(
            "/api/v1/auth/step-up", headers=sibling_headers, json={"password": password}
        )
        assert sibling_step_up.status_code == 200, sibling_step_up.text

        permissions = client.get("/api/v1/admin/access/permissions", headers=actor_headers)
        assert permissions.status_code == 200
        assert {item["name"] for item in permissions.json()} == {"audit.read", "reports.read", "roles.manage"}
        first = client.get("/api/v1/admin/access/roles", params={"limit": 1}, headers=actor_headers)
        assert first.status_code == 200, first.text
        cursor = first.json()["pagination"]["next_cursor"]
        assert cursor is not None
        second = client.get(
            "/api/v1/admin/access/roles", params={"limit": 1, "cursor": cursor}, headers=actor_headers
        )
        assert second.status_code == 200, second.text
        tenant_a_role_ids = {first.json()["roles"][0]["id"], second.json()["roles"][0]["id"]}

        sibling_roles = client.get("/api/v1/admin/access/roles", headers=sibling_headers)
        assert sibling_roles.status_code == 200
        assert {role["name"] for role in sibling_roles.json()["roles"]} == {"administrator", "reviewer"}
        # Deterministic IDs can coincide for the same role name, so use a sibling-only role for the real denial.
        sibling_created = client.post(
            "/api/v1/admin/access/roles",
            headers=sibling_headers,
            json={"name": f"sibling-{suffix}", "permissions": ["audit.read"]},
        )
        assert sibling_created.status_code == 200
        sibling_only_id = sibling_created.json()["role"]["id"]
        cross_tenant = client.patch(
            f"/api/v1/admin/access/roles/{sibling_only_id}",
            headers=actor_headers,
            json={"description": "forbidden", "expected_lifecycle_version": 1},
        )
        assert cross_tenant.status_code == 404

        created = client.post(
            "/api/v1/admin/access/roles",
            headers=actor_headers,
            json={"name": f"case-review-{suffix}", "description": "Case review", "permissions": ["audit.read"]},
        )
        assert created.status_code == 200, created.text
        custom = created.json()["role"]
        custom_id = str(custom["id"])
        assert custom_id not in tenant_a_role_ids
        duplicate = client.post(
            "/api/v1/admin/access/roles",
            headers=actor_headers,
            json={"name": f"case-review-{suffix}", "permissions": []},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "access_role_exists"

        assignment = client.put(
            f"/api/v1/admin/access/users/{target_id}/roles",
            headers=actor_headers,
            json={"role_ids": [custom_id], "expected_user_lifecycle_version": 1},
        )
        assert assignment.status_code == 200, assignment.text
        assert assignment.json()["role_ids"] == [custom_id]
        assert assignment.json()["revoked_sessions"] == 1
        assert client.get(
            "/api/v1/auth/me",
            headers={"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {target_token}"},
        ).status_code == 401

        target_token_two, target_headers_two = login(tenant_a, f"target-{suffix}")
        policy = client.put(
            f"/api/v1/admin/access/roles/{custom_id}/permissions",
            headers=actor_headers,
            json={
                "permissions": ["audit.read", "reports.read"],
                "expected_lifecycle_version": int(custom["lifecycle_version"]),
            },
        )
        assert policy.status_code == 200, policy.text
        assert policy.json()["revoked_sessions"] == 1
        assert client.get("/api/v1/auth/me", headers=target_headers_two).status_code == 401
        stale = client.put(
            f"/api/v1/admin/access/roles/{custom_id}/permissions",
            headers=actor_headers,
            json={"permissions": ["audit.read"], "expected_lifecycle_version": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "access_lifecycle_version_conflict"

        _target_token_three, target_headers_three = login(tenant_a, f"target-{suffix}")
        retired = client.patch(
            f"/api/v1/admin/access/roles/{custom_id}",
            headers=actor_headers,
            json={"active": False, "expected_lifecycle_version": 2},
        )
        assert retired.status_code == 200, retired.text
        assert retired.json()["role"]["active"] is False
        assert retired.json()["revoked_sessions"] == 1
        assert client.get("/api/v1/auth/me", headers=target_headers_three).status_code == 401
        restored = client.patch(
            f"/api/v1/admin/access/roles/{custom_id}",
            headers=actor_headers,
            json={"active": True, "expected_lifecycle_version": 3},
        )
        assert restored.status_code == 200, restored.text
        with PostgresTenantBoundary(admin_factory).transaction(tenant_a) as connection:
            assert PostgresIdentityRepository(connection).user_permissions(
                tenant_id=tenant_a, user_id=target_id
            ) == frozenset()

        with PostgresTenantBoundary(admin_factory).transaction(tenant_c) as connection:
            identity = PostgresIdentityRepository(connection)
            admin_role_id = str(
                connection.execute(
                    "SELECT id FROM reconforge.identity_roles WHERE tenant_id=%s AND name='administrator'",
                    (tenant_c,),
                ).fetchone()[0]
            )
            with pytest.raises(AccessAdministrationError) as last_manager:
                PostgresAccessAdministrationRepository(connection, tenant_c).replace_role_permissions(
                    actor_user_id=lone_id,
                    role_id=admin_role_id,
                    permissions=(),
                    expected_lifecycle_version=1,
                    as_of=datetime.now(UTC).replace(microsecond=0),
                )
            assert last_manager.value.code == "access_last_manager_forbidden"
            assert identity.user_has_permission(
                tenant_id=tenant_c, user_id=lone_id, permission_name="roles.manage"
            )
            with pytest.raises(IdentityAdministrationError) as disabled_manager:
                PostgresIdentityAdministrationRepository(connection, tenant_c).set_user_disabled(
                    actor_user_id=identity_admin_id,
                    user_id=lone_id,
                    disabled=True,
                    expected_lifecycle_version=1,
                    as_of=datetime.now(UTC).replace(microsecond=0),
                )
            assert disabled_manager.value.code == "identity_last_administrator_forbidden"

        import reconforge.infrastructure.postgres_access_administration as repository_module

        original_append = repository_module.PostgresAuditEventRepository.append

        def fail_audit(*args: object, **kwargs: object) -> object:
            raise RuntimeError("synthetic access audit failure")

        monkeypatch.setattr(repository_module.PostgresAuditEventRepository, "append", fail_audit)
        with pytest.raises(RuntimeError, match="synthetic access audit failure"), PostgresTenantBoundary(
            app_factory
        ).transaction(tenant_a) as connection:
            PostgresAccessAdministrationRepository(connection, tenant_a).create_role(
                actor_user_id=actor_id,
                name=f"rollback-{suffix}",
                description="Rollback",
                permissions=("audit.read",),
                as_of=datetime.now(UTC).replace(microsecond=0),
            )
        monkeypatch.setattr(repository_module.PostgresAuditEventRepository, "append", original_append)
        with PostgresTenantBoundary(admin_factory).transaction(tenant_a) as connection:
            assert connection.execute(
                "SELECT 1 FROM reconforge.identity_roles WHERE tenant_id=%s AND name=%s",
                (tenant_a, f"rollback-{suffix}"),
            ).fetchone() is None
            audit_actions = {
                str(row[0])
                for row in connection.execute(
                    "SELECT action FROM reconforge.domain_audit_events WHERE tenant_id=%s",
                    (tenant_a,),
                ).fetchall()
            }
        assert {
            "access.role.created",
            "access.role.permissions.replaced",
            "access.role.updated",
            "access.user.roles.replaced",
        } <= audit_actions
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            assert connection.execute(
                "SELECT 1 FROM reconforge.identity_roles WHERE tenant_id=%s AND name=%s",
                (tenant_b, f"sibling-{suffix}"),
            ).fetchone() is None

        for path in ("/api/v1/roles", "/api/v1/roles/administrator/permissions"):
            shadow = client.get(path, headers=actor_headers)
            assert shadow.status_code == 409
            assert shadow.json()["error"]["code"] == "local_identity_surface_disabled"
        serialized = permissions.text + first.text + second.text + created.text + assignment.text + policy.text
        for secret in (password, actor_token, target_token_two, sibling_token, "@sensitive.invalid"):
            assert secret not in serialized
    finally:
        admin.close()
