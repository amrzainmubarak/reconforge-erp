from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.auth.models import LocalUser


def test_scope_grant_routes_require_governed_human_authority(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.scope_grants as routes

    user = LocalUser(id="admin-a", username="admin", display_name="Admin")
    calls: list[tuple[str, object]] = []

    def authenticate(request: Any, token: str) -> AuthenticatedServerRequest | None:
        assert request_tenant_id(request) == "tenant-a"
        if token != "server-token":
            return None
        return AuthenticatedServerRequest(
            user=user,
            permissions=frozenset({"roles.manage"}),
            principal_type="user",
            step_up_active=True,
            step_up_method=None,
        )

    class Repository:
        connection = object()

    class Authority:
        def __init__(self, connection: object) -> None:
            assert connection is Repository.connection

        def grant(self, **values: object) -> None:
            calls.append(("grant", values))

        def list_active(self, **values: object) -> list[dict[str, str]]:
            calls.append(("list", values))
            return [{"id": "grant-a", "scope_type": "workspace", "scope_id": "workspace-a"}]

        def revoke(self, **values: object) -> None:
            calls.append(("revoke", values))

    def execute(request: Any, operation: Any) -> Any:
        return operation(Repository(), request_tenant_id(request))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(routes, "execute_postgres_identity", execute)
    monkeypatch.setattr(routes, "PostgresScopeAuthorityRepository", Authority)
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://scope.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {"X-ReconForge-Tenant": "tenant-a", "Authorization": "Bearer server-token"}
    created = client.post(
        "/api/v1/scope-grants",
        headers=headers,
        json={
            "principal_type": "user",
            "principal_id": "user-a",
            "scope_type": "workspace",
            "scope_id": "workspace-a",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "active"
    listed = client.get("/api/v1/scope-grants/user/user-a", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["grants"][0]["scope_id"] == "workspace-a"
    grant_id = created.json()["grant_id"]
    revoked = client.post(
        f"/api/v1/scope-grants/{grant_id}/revoke", headers=headers, json={"reason": "assignment ended"}
    )
    assert revoked.status_code == 200
    assert [name for name, _ in calls] == ["grant", "list", "revoke"]
