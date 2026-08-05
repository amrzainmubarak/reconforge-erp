from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import metrics as routes
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    db_path = tmp_path / "metrics-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_server_metrics_routes_bind_tenant_policy_without_workspace(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, headers = _client(tmp_path)
    calls: list[tuple[frozenset[str], str, None]] = []

    def enforce(_request: object, *, permissions: frozenset[str], tenant_id: str, workspace_id: None) -> None:
        calls.append((permissions, tenant_id, workspace_id))

    monkeypatch.setattr(routes, "server_metrics_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "execute_postgres_metrics", lambda _request, _operation: {"bounded": True})
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", enforce)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}

    dashboard = client.get("/api/v1/metrics/dashboard", headers=headers)
    lineage = client.get("/api/v1/metrics/lineage", headers=headers)

    assert dashboard.status_code == 200
    assert lineage.status_code == 200
    assert calls == [
        (frozenset({"metrics.read"}), "tenant-a", None),
        (frozenset({"metrics.read"}), "tenant-a", None),
    ]
