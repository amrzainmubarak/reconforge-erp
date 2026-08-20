from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import consolidation_ownership as routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations


def _body(*, approved_by: str = "reviewer-id", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "group_code": "GLOBAL-GROUP",
        "workspace": "default",
        "interest_id": "OWN-2026",
        "parent_entity_code": "PARENT",
        "subsidiary_entity_code": "SUB",
        "direct_ownership_percentage": "0.80",
        "effective_from": "2026-01-01",
        "effective_to": "",
        "version": "1.0.0",
        "source_digest": "a" * 64,
        "approved_by": approved_by,
        "approved_at": "2026-01-01T00:00:00Z",
    }
    value.update(overrides)
    return value


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str], str]:
    db_path = tmp_path / "ownership-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    auth = LocalAuthService(connection)
    auth.init_admin(username="admin", password="Secret-123")
    reviewer = auth.create_user(username="reviewer", password="Secret-123", role="admin")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}, reviewer.id


def test_ownership_api_persists_and_resolves_exact_decimal_inputs(tmp_path: Path) -> None:
    client, headers, reviewer_id = _client(tmp_path)

    created = client.post(
        "/api/v1/consolidation-ownership/interests", headers=headers, json=_body(approved_by=reviewer_id)
    )
    assert created.status_code == 200, created.text
    assert created.json()["interest"]["interest_id"] == "OWN-2026"
    assert created.json()["interest"]["prepared_by"] == "admin"
    assert created.json()["source"]["kind"] == "sqlite-consolidation-ownership"

    resolved = client.get(
        "/api/v1/consolidation-ownership/effective",
        headers=headers,
        params={"group_code": "GLOBAL-GROUP", "reporting_date": "2026-08-01"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["interests"][0]["direct_ownership_percentage"] == "0.8"
    assert resolved.json()["interests"][0]["prepared_by"] == "admin"


def test_ownership_api_rejects_float_and_unknown_fields(tmp_path: Path) -> None:
    client, headers, reviewer_id = _client(tmp_path)

    float_payload = _body(approved_by=reviewer_id, direct_ownership_percentage=0.8)
    rejected_float = client.post(
        "/api/v1/consolidation-ownership/interests", headers=headers, json=float_payload
    )
    assert rejected_float.status_code == 422

    unknown = _body(approved_by=reviewer_id, unexpected=True)
    rejected_unknown = client.post("/api/v1/consolidation-ownership/interests", headers=headers, json=unknown)
    assert rejected_unknown.status_code == 422

    missing_approver = client.post(
        "/api/v1/consolidation-ownership/interests",
        headers=headers,
        json=_body(approved_by="does-not-exist"),
    )
    assert missing_approver.status_code == 400
    assert missing_approver.json()["error"]["code"] == "consolidation_ownership_approver_invalid"

    connection = connect(tmp_path / "ownership-api.db")
    unauthorized = LocalAuthService(connection).create_user(
        username="auditor", password="Secret-123", role="auditor-readonly"
    )
    connection.close()
    unauthorized_response = client.post(
        "/api/v1/consolidation-ownership/interests",
        headers=headers,
        json=_body(approved_by=unauthorized.id),
    )
    assert unauthorized_response.status_code == 403
    assert unauthorized_response.json()["error"]["code"] == "consolidation_ownership_approver_unauthorized"


def test_ownership_api_server_branch_binds_authenticated_workspace(tmp_path: Path, monkeypatch: Any) -> None:
    client, headers, reviewer_id = _client(tmp_path)
    captured: dict[str, object] = {}
    scoped_permissions: list[dict[str, object]] = []

    class Repository:
        connection = object()

        def save_interest(self, interest: object, **kwargs: object) -> dict[str, object]:
            captured["interest"] = interest
            captured.update(kwargs)
            return {"interest_id": "OWN-2026", "workspace_id": kwargs["workspace"]}

        def resolve_effective(self, **kwargs: object) -> tuple[object, ...]:
            captured["resolve"] = kwargs
            return ()

    repository = Repository()

    def execute(_request: object, operation: object) -> object:
        return operation(repository, "tenant-a")  # type: ignore[operator]

    monkeypatch.setattr(routes, "server_consolidation_ownership_enabled", lambda _request: True)
    monkeypatch.setattr(
        routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(routes, "_verify_postgres_approver", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant-a", "workspace-a"))
    monkeypatch.setattr(routes, "execute_postgres_consolidation_ownership", execute)

    created = client.post(
        "/api/v1/consolidation-ownership/interests",
        headers=headers,
        json=_body(workspace="default", approved_by=reviewer_id),
    )
    assert created.status_code == 200, created.text
    assert created.json()["source"]["kind"] == "postgresql-consolidation-ownership"
    assert scoped_permissions == [
        {"permission": "finance_core.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"}
    ]
    assert captured["workspace"] == "workspace-a"
    assert captured["actor_label"] == captured["interest"].prepared_by  # type: ignore[union-attr]

    sibling = client.post(
        "/api/v1/consolidation-ownership/interests",
        headers=headers,
        json=_body(workspace="workspace-b", interest_id="OWN-SIBLING", approved_by=reviewer_id),
    )
    assert sibling.status_code == 403
    assert sibling.json()["error"]["code"] == "workspace_scope_denied"
