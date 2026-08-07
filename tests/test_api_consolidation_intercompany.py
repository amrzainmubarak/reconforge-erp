from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import consolidation_intercompany as routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from tests.test_intercompany_elimination import _reciprocal_lines


def _body() -> dict[str, object]:
    return {
        "workspace": "default",
        "reporting_currency": "USD",
        "version": "1.0.0",
        "prepared_at": "2026-08-05T12:00:00Z",
        "lines": [line.to_dict() for line in _reciprocal_lines()],
    }


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    db_path = tmp_path / "intercompany-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_intercompany_api_requires_server_profile(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    unauthenticated = client.post("/api/v1/consolidation-intercompany-eliminations", json=_body())
    assert unauthenticated.status_code == 401
    unavailable = client.post(
        "/api/v1/consolidation-intercompany-eliminations", headers=headers, json=_body()
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "consolidation_intercompany_unavailable"


def test_intercompany_api_computes_with_authenticated_actor(tmp_path: Path, monkeypatch: Any) -> None:
    client, headers = _client(tmp_path)
    captured: dict[str, object] = {}

    class Repository:
        def persist(self, lines: object, result: object, **kwargs: object) -> dict[str, object]:
            captured["lines"] = lines
            captured["result"] = result
            captured["kwargs"] = kwargs
            return {"id": "ice-" + "a" * 32, "posting": "not_available"}

        def get(self, artifact_id: str, **_: object) -> dict[str, object]:
            return {"id": artifact_id, "workspace_id": "default", "posting": "not_available"}

    repository = Repository()

    def execute(_request: object, operation: object) -> object:
        return operation(repository, "tenant-a")  # type: ignore[operator]

    monkeypatch.setattr(routes, "server_consolidation_intercompany_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "execute_postgres_consolidation_intercompany", execute)
    monkeypatch.setattr(
        routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope(
            tenant_id="tenant-a", workspace_id="default", organization_id="org-a", legal_entity_id="entity-a"
        ),
    )
    scoped_permissions: list[dict[str, object]] = []
    monkeypatch.setattr(
        routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    created = client.post("/api/v1/consolidation-intercompany-eliminations", headers=headers, json=_body())
    assert created.status_code == 200, created.text
    assert created.json()["artifact"]["posting"] == "not_available"
    actor_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    assert captured["result"].prepared_by == actor_id  # type: ignore[union-attr]
    assert captured["kwargs"]["workspace"] == "default"  # type: ignore[index]

    loaded = client.get(
        "/api/v1/consolidation-intercompany-eliminations/ice-" + "a" * 32,
        headers=headers,
    )
    assert loaded.status_code == 200
    assert scoped_permissions == [
        {
            "permission": "finance_core.manage",
            "tenant_id": "tenant-a",
            "workspace_id": "default",
            "organization_id": "org-a",
            "entity_id": "entity-a",
        },
        {
            "permission": "finance_core.read",
            "tenant_id": "tenant-a",
            "workspace_id": "default",
            "organization_id": "org-a",
            "entity_id": "entity-a",
        },
    ]
    invalid = _body()
    invalid["unexpected"] = True
    assert client.post(
        "/api/v1/consolidation-intercompany-eliminations", headers=headers, json=invalid
    ).status_code == 422
