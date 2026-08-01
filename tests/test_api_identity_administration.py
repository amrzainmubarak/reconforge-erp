from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.application.identity_administration import (
    IdentitySessionPage,
    IdentitySessionSummary,
    IdentityUserPage,
    IdentityUserSummary,
    SessionRevocation,
    UserStatusChange,
)
from reconforge.auth import LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.db import connect, run_migrations

NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def _user(user_id: str, username: str, *, disabled: bool = False, version: int = 1) -> IdentityUserSummary:
    return IdentityUserSummary(
        id=user_id,
        username=username,
        display_name=f"Display {username}",
        disabled=disabled,
        lifecycle_version=version,
        roles=("administrator",),
        active_sessions=0 if disabled else 1,
        created_at="2026-07-29T19:00:00Z",
        disabled_at="2026-07-29T20:00:00Z" if disabled else None,
        state_digest="a" * 64,
    )


def _session(*, version: int = 1, revoked: bool = False) -> IdentitySessionSummary:
    return IdentitySessionSummary(
        id="session-target",
        user_id="user-target",
        username="target",
        status="revoked" if revoked else "active",
        lifecycle_version=version,
        created_at="2026-07-29T19:30:00Z",
        expires_at="2026-07-29T21:00:00Z",
        last_used_at=None,
        revoked_at="2026-07-29T20:00:00Z" if revoked else None,
        revocation_reason_code="security_response" if revoked else None,
        client_ip_recorded=True,
        user_agent_recorded=True,
        state_digest="b" * 64,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_users(self, **kwargs: object) -> IdentityUserPage:
        self.calls.append(("list_users", kwargs))
        if kwargs["after_username"] is None:
            return IdentityUserPage((_user("user-admin", "admin"),), "admin", "user-admin")
        return IdentityUserPage((_user("user-target", "target"),))

    def set_user_disabled(self, **kwargs: object) -> UserStatusChange:
        self.calls.append(("set_user_disabled", kwargs))
        return UserStatusChange(_user("user-target", "target", disabled=True, version=2), True, 1, "audit-1")

    def list_sessions(self, **kwargs: object) -> IdentitySessionPage:
        self.calls.append(("list_sessions", kwargs))
        return IdentitySessionPage((_session(),))

    def revoke_session(self, **kwargs: object) -> SessionRevocation:
        self.calls.append(("revoke_session", kwargs))
        return SessionRevocation(_session(version=2, revoked=True), True, False, "audit-2")


def test_identity_admin_http_is_human_mfa_governed_paginated_redacted_and_disables_shadow_users(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.identity_administration as routes

    repository = _Repository()
    user = LocalUser(id="user-admin", username="admin", display_name="Admin")

    def authenticate(request: Any, token: str) -> AuthenticatedServerRequest | None:
        assert request_tenant_id(request) == "tenant-a"
        profiles = {
            "human-ok": ("user", frozenset({"users.manage"}), True, "webauthn_user_verified"),
            "human-no-permission": ("user", frozenset(), True, "webauthn_user_verified"),
            "human-no-step-up": ("user", frozenset({"users.manage"}), False, None),
            "human-password-only": ("user", frozenset({"users.manage"}), True, "password_reauthentication"),
            "service": ("service_account", frozenset({"users.manage"}), True, "webauthn_user_verified"),
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
    monkeypatch.setattr(routes, "execute_postgres_identity_administration", execute)
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "control.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"identity-administration-test-key-32-bytes",
            webauthn_runtime=WebAuthnRuntime(
                rp_id="example.test",
                rp_name="ReconForge",
                allowed_origins=("https://admin.example.test",),
            ),
        )
    )

    def headers(token: str) -> dict[str, str]:
        return {"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/admin/identity/users", headers=headers("human-no-permission")).status_code == 403
    assert (
        client.get("/api/v1/admin/identity/users", headers=headers("human-no-step-up")).json()["error"]["code"]
        == "step_up_required"
    )
    assert (
        client.get("/api/v1/admin/identity/users", headers=headers("human-password-only")).json()["error"]["code"]
        == "mfa_required"
    )
    assert client.get("/api/v1/admin/identity/users", headers=headers("service")).status_code == 403

    first = client.get("/api/v1/admin/identity/users?limit=1", headers=headers("human-ok"))
    assert first.status_code == 200, first.text
    cursor = first.json()["pagination"]["next_cursor"]
    assert cursor
    second = client.get(
        "/api/v1/admin/identity/users", params={"limit": 1, "cursor": cursor}, headers=headers("human-ok")
    )
    assert second.status_code == 200 and second.json()["users"][0]["id"] == "user-target"
    tampered = client.get(
        "/api/v1/admin/identity/users", params={"cursor": cursor[:-1] + "A"}, headers=headers("human-ok")
    )
    assert tampered.status_code == 400

    sessions = client.get(
        "/api/v1/admin/identity/sessions", params={"user_id": "user-target"}, headers=headers("human-ok")
    )
    assert sessions.status_code == 200, sessions.text
    disabled = client.post(
        "/api/v1/admin/identity/users/user-target/status",
        headers=headers("human-ok"),
        json={"disabled": True, "expected_lifecycle_version": 1},
    )
    assert disabled.status_code == 200 and disabled.json()["revoked_sessions"] == 1
    revoked = client.post(
        "/api/v1/admin/identity/sessions/session-target/revoke",
        headers=headers("human-ok"),
        json={"expected_lifecycle_version": 1, "reason_code": "security_response"},
    )
    assert revoked.status_code == 200 and revoked.json()["session"]["status"] == "revoked"
    hostile = client.post(
        "/api/v1/admin/identity/users/user-target/status",
        headers=headers("human-ok"),
        json={"disabled": True, "expected_lifecycle_version": 1, "password": "not-accepted"},
    )
    assert hostile.status_code == 422
    self_disable = client.post(
        "/api/v1/admin/identity/users/user-admin/status",
        headers=headers("human-ok"),
        json={"disabled": True, "expected_lifecycle_version": 1},
    )
    assert self_disable.status_code == 409
    assert self_disable.json()["error"]["code"] == "identity_self_disable_forbidden"

    shadow = client.get("/api/v1/users", headers=headers("human-ok"))
    assert shadow.status_code == 409
    assert shadow.json()["error"]["code"] == "local_identity_surface_disabled"
    serialized = first.text + second.text + sessions.text + disabled.text + revoked.text
    for forbidden in ("password", "token_hash", "client_ip\"", "user_agent\"", "admin@example.test"):
        assert forbidden not in serialized
    assert repository.calls[1][1]["after_username"] == "admin"
    assert repository.calls[1][1]["after_user_id"] == "user-admin"


def test_identity_admin_requires_server_profile_and_operator_cursor_key(tmp_path: Path) -> None:
    db_path = tmp_path / "local.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    assert login.status_code == 200
    unavailable = client.get(
        "/api/v1/admin/identity/users",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "identity_administration_unavailable"
