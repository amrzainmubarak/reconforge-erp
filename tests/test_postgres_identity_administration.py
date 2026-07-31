from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.identity_administration import IdentityAdministrationError
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_identity_administration import (
    PostgresIdentityAdministrationRepository,
)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_identity_admin_http_is_atomic_tenant_isolated_and_invalidates_sessions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"identity_admin_a_{suffix}"
    tenant_b = f"identity_admin_b_{suffix}"
    tenant_c = f"identity_admin_c_{suffix}"
    password = "Synthetic-identity-admin-password-123!"
    actor_id = f"actor-{suffix}"
    backup_id = f"backup-{suffix}"
    target_id = f"target-{suffix}"
    sibling_id = f"sibling-{suffix}"
    lone_admin_id = f"lone-{suffix}"
    observer_id = f"observer-{suffix}"
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
                identity.create_permission(
                    tenant_id=tenant,
                    permission_name="users.manage",
                    description="Govern authoritative identities",
                )
                identity.create_role(tenant_id=tenant, role_name="administrator")
                identity.create_role(tenant_id=tenant, role_name="observer")
                identity.grant_permission(
                    tenant_id=tenant,
                    role_name="administrator",
                    permission_name="users.manage",
                )
                for user_id, username, role in users:
                    identity.create_user(
                        tenant_id=tenant,
                        user_id=user_id,
                        username=username,
                        display_name=f"Synthetic {username}",
                        email=f"{username}@sensitive.invalid",
                        password=password,
                        role_name=role,
                    )

        provision(
            tenant_a,
            (
                (actor_id, f"actor-{suffix}", "administrator"),
                (backup_id, f"backup-{suffix}", "administrator"),
                (target_id, f"target-{suffix}", "observer"),
            ),
        )
        provision(tenant_b, ((sibling_id, f"sibling-{suffix}", "administrator"),))
        provision(
            tenant_c,
            (
                (lone_admin_id, f"lone-{suffix}", "administrator"),
                (observer_id, f"observer-{suffix}", "observer"),
            ),
        )

        client = TestClient(
            create_api_app(
                tmp_path / "control.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
                cursor_signing_key=b"live-e191-cursor-signing-key-32-bytes",
            )
        )

        def login(tenant: str, username: str) -> tuple[str, dict[str, str]]:
            tenant_headers = {"X-ReconForge-Tenant": tenant}
            response = client.post(
                "/api/v1/auth/login",
                headers=tenant_headers,
                json={"username": username, "password": password},
            )
            assert response.status_code == 200, response.text
            token = str(response.json()["access_token"])
            return token, {**tenant_headers, "Authorization": f"Bearer {token}"}

        actor_token, actor_headers = login(tenant_a, f"actor-{suffix}")
        target_token_one, target_headers = login(tenant_a, f"target-{suffix}")
        target_token_two, _ = login(tenant_a, f"target-{suffix}")
        sibling_token, sibling_headers = login(tenant_b, f"sibling-{suffix}")

        before_step_up = client.get("/api/v1/admin/identity/users", headers=actor_headers)
        assert before_step_up.status_code == 403
        assert before_step_up.json()["error"]["code"] == "step_up_required"
        step_up = client.post(
            "/api/v1/auth/step-up", headers=actor_headers, json={"password": password}
        )
        assert step_up.status_code == 200, step_up.text

        seen_users: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            params = {"limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            page = client.get("/api/v1/admin/identity/users", headers=actor_headers, params=params)
            assert page.status_code == 200, page.text
            seen_users.extend(page.json()["users"])
            cursor = page.json()["pagination"]["next_cursor"]
            if cursor is None:
                break
        assert {item["id"] for item in seen_users} == {actor_id, backup_id, target_id}
        assert sibling_id not in {item["id"] for item in seen_users}
        target_version = next(int(item["lifecycle_version"]) for item in seen_users if item["id"] == target_id)
        serialized = "".join(str(item) for item in seen_users)
        for secret in (password, target_token_one, target_token_two, sibling_token, "@sensitive.invalid"):
            assert secret not in serialized

        target_sessions = client.get(
            "/api/v1/admin/identity/sessions",
            headers=actor_headers,
            params={"user_id": target_id, "limit": 1},
        )
        assert target_sessions.status_code == 200, target_sessions.text
        session_cursor = target_sessions.json()["pagination"]["next_cursor"]
        assert session_cursor is not None
        mismatch = client.get(
            "/api/v1/admin/identity/sessions",
            headers=actor_headers,
            params={"user_id": actor_id, "cursor": session_cursor},
        )
        assert mismatch.status_code == 400
        for forbidden in (target_token_one, target_token_two, "client_ip\"", "user_agent\""):
            assert forbidden not in target_sessions.text

        with PostgresTenantBoundary(admin_factory).transaction(tenant_b) as connection:
            sibling_session_id = str(
                connection.execute(
                    "SELECT id FROM reconforge.identity_sessions WHERE tenant_id=%s AND token_hash=%s",
                    (tenant_b, _token_hash(sibling_token)),
                ).fetchone()[0]
            )
        sibling_denied = client.post(
            f"/api/v1/admin/identity/sessions/{sibling_session_id}/revoke",
            headers=actor_headers,
            json={"expected_lifecycle_version": 1, "reason_code": "security_response"},
        )
        assert sibling_denied.status_code == 404

        disabled = client.post(
            f"/api/v1/admin/identity/users/{target_id}/status",
            headers=actor_headers,
            json={"disabled": True, "expected_lifecycle_version": target_version},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["transitioned"] is True
        assert disabled.json()["revoked_sessions"] == 2
        assert disabled.json()["audit_event_id"]
        for token in (target_token_one, target_token_two):
            denied = client.get(
                "/api/v1/auth/me",
                headers={"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {token}"},
            )
            assert denied.status_code == 401
        relogin_disabled = client.post(
            "/api/v1/auth/login",
            headers={"X-ReconForge-Tenant": tenant_a},
            json={"username": f"target-{suffix}", "password": password},
        )
        assert relogin_disabled.status_code == 401
        stale = client.post(
            f"/api/v1/admin/identity/users/{target_id}/status",
            headers=actor_headers,
            json={"disabled": False, "expected_lifecycle_version": target_version},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "identity_lifecycle_version_conflict"
        self_disable = client.post(
            f"/api/v1/admin/identity/users/{actor_id}/status",
            headers=actor_headers,
            json={"disabled": True, "expected_lifecycle_version": 1},
        )
        assert self_disable.status_code == 409
        assert self_disable.json()["error"]["code"] == "identity_self_disable_forbidden"

        enabled = client.post(
            f"/api/v1/admin/identity/users/{target_id}/status",
            headers=actor_headers,
            json={"disabled": False, "expected_lifecycle_version": target_version + 1},
        )
        assert enabled.status_code == 200, enabled.text
        restored_token, restored_headers = login(tenant_a, f"target-{suffix}")

        import reconforge.infrastructure.postgres_identity_administration as repository_module

        original_append = repository_module.PostgresAuditEventRepository.append

        def fail_audit(*args: object, **kwargs: object) -> object:
            raise RuntimeError("synthetic audit failure")

        monkeypatch.setattr(repository_module.PostgresAuditEventRepository, "append", fail_audit)
        with pytest.raises(RuntimeError, match="synthetic audit failure"), PostgresTenantBoundary(
            PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
        ).transaction(tenant_a) as connection:
            PostgresIdentityAdministrationRepository(connection, tenant_a).set_user_disabled(
                actor_user_id=actor_id,
                user_id=target_id,
                disabled=True,
                expected_lifecycle_version=target_version + 2,
                as_of=datetime.now(UTC).replace(microsecond=0),
            )
        monkeypatch.setattr(repository_module.PostgresAuditEventRepository, "append", original_append)
        assert client.get("/api/v1/auth/me", headers=restored_headers).status_code == 200

        with PostgresTenantBoundary(admin_factory).transaction(tenant_c) as connection:
            with pytest.raises(IdentityAdministrationError) as last_admin:
                PostgresIdentityAdministrationRepository(connection, tenant_c).set_user_disabled(
                    actor_user_id=observer_id,
                    user_id=lone_admin_id,
                    disabled=True,
                    expected_lifecycle_version=1,
                    as_of=datetime.now(UTC).replace(microsecond=0),
                )
            assert last_admin.value.code == "identity_last_administrator_forbidden"

        with PostgresTenantBoundary(admin_factory).transaction(tenant_a) as connection:
            actor_session_id = str(
                connection.execute(
                    "SELECT id FROM reconforge.identity_sessions WHERE tenant_id=%s AND token_hash=%s",
                    (tenant_a, _token_hash(actor_token)),
                ).fetchone()[0]
            )
            audit_actions = {
                str(row[0])
                for row in connection.execute(
                    "SELECT action FROM reconforge.domain_audit_events WHERE tenant_id=%s",
                    (tenant_a,),
                ).fetchall()
            }
        revoke_self = client.post(
            f"/api/v1/admin/identity/sessions/{actor_session_id}/revoke",
            headers=actor_headers,
            json={"expected_lifecycle_version": 1, "reason_code": "user_request"},
        )
        assert revoke_self.status_code == 200, revoke_self.text
        assert revoke_self.json()["revoked_current_session"] is True
        assert client.get("/api/v1/admin/identity/users", headers=actor_headers).status_code == 401
        assert "identity.user.disabled" in audit_actions
        assert "identity.user.enabled" in audit_actions

        sibling_me = client.get("/api/v1/auth/me", headers=sibling_headers)
        assert sibling_me.status_code == 200
        assert restored_token not in sibling_me.text
    finally:
        admin.close()
