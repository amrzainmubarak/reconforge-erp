from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import consolidation_deferred_tax as routes
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from tests.test_consolidation_deferred_tax import _request


def _body() -> dict[str, object]:
    payload = _request().to_dict()
    payload.pop("prepared_by", None)
    return payload


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    db_path = tmp_path / "deferred-tax-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_deferred_tax_api_is_server_profile_only_and_authenticated(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}

    unauthenticated = client.post("/api/v1/consolidation-deferred-tax", json=_body())
    assert unauthenticated.status_code == 401
    unavailable = client.post("/api/v1/consolidation-deferred-tax", headers=headers, json=_body())
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "consolidation_deferred_tax_unavailable"


def test_deferred_tax_api_rebuilds_typed_request_and_uses_authenticated_actor(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, headers = _client(tmp_path)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}
    captured: dict[str, object] = {}

    class Repository:
        def persist(self, request: object, result: object, **_: object) -> dict[str, object]:
            captured["request"] = request
            captured["result"] = result
            return {
                "id": "dtax-" + "a" * 32,
                "posted": False,
                "result_digest": result.result_digest,  # type: ignore[union-attr]
            }

        def get(self, artifact_id: str, **_: object) -> dict[str, object]:
            return {"id": artifact_id, "posted": False}

    repository = Repository()

    def execute(_request: object, operation: object) -> object:
        return operation(repository, "tenant-a")  # type: ignore[operator]

    monkeypatch.setattr(routes, "server_deferred_tax_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "execute_postgres_deferred_tax", execute)

    actor_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    created = client.post("/api/v1/consolidation-deferred-tax", headers=headers, json=_body())
    assert created.status_code == 200, created.text
    assert created.json()["artifact"]["posted"] is False
    assert captured["request"].prepared_by == actor_id  # type: ignore[union-attr]
    assert captured["request"].approved_by == "reviewer"  # type: ignore[union-attr]

    loaded = client.get(
        "/api/v1/consolidation-deferred-tax/dtax-" + "a" * 32,
        headers=headers,
    )
    assert loaded.status_code == 200
    assert loaded.json()["artifact"]["posted"] is False

    invalid = _body()
    invalid["unexpected"] = True
    rejected = client.post("/api/v1/consolidation-deferred-tax", headers=headers, json=invalid)
    assert rejected.status_code == 422


def test_deferred_tax_server_routes_re_evaluate_tenant_policy_without_workspace(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, headers = _client(tmp_path)
    captured: list[tuple[frozenset[str], str, None, object]] = []

    def enforce(
        _request: object,
        *,
        permissions: frozenset[str],
        tenant_id: str,
        workspace_id: None,
        amount: object = None,
    ) -> None:
        captured.append((permissions, tenant_id, workspace_id, amount))

    monkeypatch.setattr(routes, "server_deferred_tax_enabled", lambda _request: True)
    monkeypatch.setattr(
        routes,
        "execute_postgres_deferred_tax",
        lambda _request, _operation: {"id": "dtax-" + "a" * 32, "posted": False},
    )
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", enforce)
    headers = {**headers, "X-ReconForge-Tenant": "tenant-a"}

    created = client.post("/api/v1/consolidation-deferred-tax", headers=headers, json=_body())
    assert created.status_code == 200
    assert captured == [(frozenset({"finance_core.manage"}), "tenant-a", None, Decimal("270.00"))]

    loaded = client.get(
        "/api/v1/consolidation-deferred-tax/dtax-" + "a" * 32,
        headers=headers,
    )
    assert loaded.status_code == 200
    assert captured[-1] == (frozenset({"finance_core.read", "finance_core.manage"}), "tenant-a", None, None)
