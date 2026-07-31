from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres_privileged_sessions import PrivilegedSessionAssurance


def test_human_privileged_route_requires_current_session_step_up(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.auth as auth_routes

    user = LocalUser(
        id="human-1",
        username="controller",
        display_name="Controller",
        created_at="2026-07-29T00:00:00Z",
    )
    token = "human-session-token"
    step_up_active = False

    def authenticate(request: Any, supplied: str) -> AuthenticatedServerRequest | None:
        if request_tenant_id(request) != "tenant-a" or supplied != token:
            return None
        return AuthenticatedServerRequest(
            user=user,
            permissions=frozenset({"roles.manage"}),
            principal_type="user",
            session_id="ses-human-1",
            step_up_active=step_up_active,
            step_up_expires_at="2026-07-29T00:10:00Z" if step_up_active else None,
        )

    class FakePrivilegedRepository:
        def __init__(self, connection: Any) -> None:
            assert connection is not None

        def reauthenticate(self, **values: Any) -> PrivilegedSessionAssurance | None:
            nonlocal step_up_active
            assert values["tenant_id"] == "tenant-a"
            assert values["token"] == token
            assert values["user_id"] == user.id
            if values["password"] != "correct-password":
                return None
            step_up_active = True
            return PrivilegedSessionAssurance("ses-human-1", True, "2026-07-29T00:10:00Z")

    repository = SimpleNamespace(
        connection=object(),
        user_roles=lambda **_: ["controller"],
    )

    def execute(request: Any, operation: Any) -> Any:
        return operation(repository, request_tenant_id(request))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(auth_routes, "execute_postgres_identity", execute)
    monkeypatch.setattr(auth_routes, "PostgresPrivilegedSessionRepository", FakePrivilegedRepository)

    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"}

    denied = client.get("/api/v1/roles", headers=headers)
    wrong = client.post("/api/v1/auth/step-up", headers=headers, json={"password": "wrong-password"})
    accepted = client.post("/api/v1/auth/step-up", headers=headers, json={"password": "correct-password"})
    authoritative_boundary = client.get("/api/v1/roles", headers=headers)
    me = client.get("/api/v1/auth/me", headers=headers)

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "step_up_required"
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {
        "method": "password_reauthentication",
        "expires_at": "2026-07-29T00:10:00Z",
    }
    assert authoritative_boundary.status_code == 409
    assert authoritative_boundary.json()["error"]["code"] == "local_identity_surface_disabled"
    assert me.json()["step_up_active"] is True


def test_service_principal_cannot_step_up(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies

    user = LocalUser(id="svc-1", username="worker", display_name="Worker", created_at="2026-07-29T00:00:00Z")

    def authenticate(request: Any, supplied: str) -> AuthenticatedServerRequest | None:
        request_tenant_id(request)
        if supplied != "rfa_test":
            return None
        return AuthenticatedServerRequest(
            user=user,
            permissions=frozenset({"db.read"}),
            principal_type="service_account",
            credential_id="credential-1",
        )

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
        )
    )
    response = client.post(
        "/api/v1/auth/step-up",
        headers={"X-ReconForge-Tenant": "tenant-a", "Authorization": "Bearer rfa_test"},
        json={"password": "irrelevant"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_principal_required"
