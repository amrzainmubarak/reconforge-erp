from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.application.access_administration import (
    AccessPermissionSummary,
    AccessRoleChange,
    AccessRolePage,
    AccessRoleSummary,
    UserRoleAssignmentChange,
)
from reconforge.auth import LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.db import connect, run_migrations


def _role(*, name: str = "administrator", version: int = 1) -> AccessRoleSummary:
    return AccessRoleSummary(
        id=f"role-{name}",
        name=name,
        description=name.title(),
        active=True,
        lifecycle_version=version,
        permissions=("roles.manage",),
        active_user_count=1,
        created_at="2026-07-29T20:00:00Z",
        updated_at="2026-07-29T20:00:00Z",
        retired_at=None,
        state_digest="a" * 64,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.connection = _PolicyConnection()

    def list_permissions(self) -> tuple[AccessPermissionSummary, ...]:
        self.calls.append(("list_permissions", {}))
        return (AccessPermissionSummary("roles.manage", "Manage access", 1, "b" * 64),)

    def list_roles(self, **kwargs: object) -> AccessRolePage:
        self.calls.append(("list_roles", kwargs))
        if kwargs["after_name"] is None:
            return AccessRolePage((_role(),), "administrator", "role-administrator")
        return AccessRolePage((_role(name="reviewer"),))

    def create_role(self, **kwargs: object) -> AccessRoleChange:
        self.calls.append(("create_role", kwargs))
        return AccessRoleChange(_role(name=str(kwargs["name"])), True, 0, "audit-1")

    def update_role(self, **kwargs: object) -> AccessRoleChange:
        self.calls.append(("update_role", kwargs))
        return AccessRoleChange(_role(version=2), True, 1, "audit-2")

    def replace_role_permissions(self, **kwargs: object) -> AccessRoleChange:
        self.calls.append(("replace_role_permissions", kwargs))
        return AccessRoleChange(_role(version=2), True, 1, "audit-3")

    def replace_user_roles(self, **kwargs: object) -> UserRoleAssignmentChange:
        self.calls.append(("replace_user_roles", kwargs))
        return UserRoleAssignmentChange(
            "user-reviewer",
            "reviewer",
            2,
            ("role-reviewer",),
            ("reviewer",),
            True,
            1,
            "audit-4",
            "c" * 64,
        )


class _PolicyCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)


class _PolicyConnection:
    def execute(self, sql: str, _parameters: tuple[object, ...]) -> _PolicyCursor:
        if "identity_user_roles" in sql:
            return _PolicyCursor(
                [
                    {"principal_id": "user-1", "role_id": "role-prepare", "role_name": "preparer", "permission_name": "close.prepare"},
                    {"principal_id": "user-1", "role_id": "role-approve", "role_name": "approver", "permission_name": "close.approve"},
                ]
            )
        if "service_accounts" in sql:
            return _PolicyCursor([{"principal_id": "svc-1", "permission_name": "close.manage"}])
        return _PolicyCursor([{"active": True}])


def test_access_admin_http_is_human_mfa_governed_paginated_and_closes_sqlite_roles(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.access_administration as routes

    repository = _Repository()
    user = LocalUser(id="user-admin", username="admin", display_name="Admin")

    def authenticate(request: Any, token: str) -> AuthenticatedServerRequest | None:
        assert request_tenant_id(request) == "tenant-a"
        profiles = {
            "human-ok": ("user", frozenset({"roles.manage", "security.policy.manage"}), True, "webauthn_user_verified"),
            "human-no-permission": ("user", frozenset(), True, "webauthn_user_verified"),
            "human-no-step-up": ("user", frozenset({"roles.manage"}), False, None),
            "human-password-only": ("user", frozenset({"roles.manage"}), True, "password_reauthentication"),
            "service": ("service_account", frozenset({"roles.manage"}), True, "webauthn_user_verified"),
        }
        profile = profiles.get(token)
        if profile is None:
            return None
        principal_type, permissions, active, method = profile
        return AuthenticatedServerRequest(
            user=user,
            permissions=permissions,
            principal_type=principal_type,
            session_id="session-admin",
            step_up_active=active,
            step_up_method=method,
        )

    def execute(request: Any, operation: Any) -> Any:
        return operation(repository, request_tenant_id(request))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(routes, "execute_postgres_access_administration", execute)
    root = tmp_path / "tenants"
    root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "missing-control.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"access-administration-test-key-32-bytes",
            webauthn_runtime=WebAuthnRuntime(
                rp_id="example.test",
                rp_name="ReconForge",
                allowed_origins=("https://admin.example.test",),
            ),
        )
    )

    def headers(token: str) -> dict[str, str]:
        return {"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/admin/access/roles", headers=headers("human-no-permission")).status_code == 403
    assert (
        client.get("/api/v1/admin/access/roles", headers=headers("human-no-step-up")).json()["error"]["code"]
        == "step_up_required"
    )
    assert (
        client.get("/api/v1/admin/access/roles", headers=headers("human-password-only")).json()["error"]["code"]
        == "mfa_required"
    )
    assert client.get("/api/v1/admin/access/roles", headers=headers("service")).status_code == 403

    permissions = client.get("/api/v1/admin/access/permissions", headers=headers("human-ok"))
    assert permissions.status_code == 200 and permissions.json()[0]["name"] == "roles.manage"
    first = client.get("/api/v1/admin/access/roles?limit=1", headers=headers("human-ok"))
    assert first.status_code == 200, first.text
    cursor = first.json()["pagination"]["next_cursor"]
    second = client.get(
        "/api/v1/admin/access/roles", params={"limit": 1, "cursor": cursor}, headers=headers("human-ok")
    )
    assert second.status_code == 200 and second.json()["roles"][0]["name"] == "reviewer"
    mismatch = client.get(
        "/api/v1/admin/access/roles",
        params={"cursor": cursor, "include_retired": True},
        headers=headers("human-ok"),
    )
    assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "cursor_context_mismatch"

    created = client.post(
        "/api/v1/admin/access/roles",
        headers=headers("human-ok"),
        json={"name": "reviewer", "description": "Reviewer", "permissions": ["audit.read"]},
    )
    assert created.status_code == 200 and created.json()["transitioned"] is True
    updated = client.patch(
        "/api/v1/admin/access/roles/role-administrator",
        headers=headers("human-ok"),
        json={"description": "Admin", "expected_lifecycle_version": 1},
    )
    assert updated.status_code == 200 and updated.json()["role"]["lifecycle_version"] == 2
    policy = client.put(
        "/api/v1/admin/access/roles/role-administrator/permissions",
        headers=headers("human-ok"),
        json={"permissions": ["roles.manage"], "expected_lifecycle_version": 1},
    )
    assert policy.status_code == 200 and policy.json()["revoked_sessions"] == 1
    assignment = client.put(
        "/api/v1/admin/access/users/user-reviewer/roles",
        headers=headers("human-ok"),
        json={"role_ids": ["role-reviewer"], "expected_user_lifecycle_version": 1},
    )
    assert assignment.status_code == 200 and assignment.json()["role_names"] == ["reviewer"]
    analysis = client.post(
        "/api/v1/admin/access/policy-analysis",
        headers=headers("human-ok"),
        json={"approved_by": "reviewer", "approved_at": "2026-08-03T08:00:00Z"},
    )
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["status"] == "conflicts"
    assert "sod_permission_overlap" in {finding["code"] for finding in analysis.json()["findings"]}
    hostile = client.post(
        "/api/v1/admin/access/roles",
        headers=headers("human-ok"),
        json={"name": "bad", "permissions": [], "password": "not-accepted"},
    )
    assert hostile.status_code == 422

    for path in ("/api/v1/roles", "/api/v1/roles/administrator/permissions"):
        shadow = client.get(path, headers=headers("human-ok"))
        assert shadow.status_code == 409
        assert shadow.json()["error"]["code"] == "local_identity_surface_disabled"
    assert repository.calls[2][1]["after_name"] == "administrator"
    serialized = permissions.text + first.text + second.text + created.text + updated.text + policy.text
    for forbidden in ("password", "token", "email", "client_ip", "user_agent"):
        assert forbidden not in serialized.casefold()


def test_access_admin_requires_server_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "local.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    unavailable = client.get(
        "/api/v1/admin/access/roles",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "access_administration_unavailable"
