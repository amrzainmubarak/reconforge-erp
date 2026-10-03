"""Real local API sessions exercise inbox permissions, isolation and CSRF."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes.notification_inbox import router
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.notification_inbox_schema import SQLITE_NOTIFICATION_INBOX_SQL


def _client(tmp_path: Path) -> tuple[TestClient, str]:
    path = tmp_path / "inbox-api.db"
    run_migrations(path)
    with connect(path) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='notification_inbox'").fetchone():
            connection.executescript(SQLITE_NOTIFICATION_INBOX_SQL)
        for workspace in ("default", "sibling"):
            connection.execute("INSERT INTO workspaces(id,name,local_first_note,created_at) VALUES(?,?,'synthetic','2026-10-03T00:00:00Z')", (workspace, workspace))
        connection.commit()
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Synthetic-123")
        recipient = auth.create_user(username="reviewer", password="Synthetic-123", role="reviewer")
        auth.create_user(username="other", password="Synthetic-123", role="auditor-readonly")
    app = create_api_app(path)
    if not any(getattr(route, "path", "") == "/api/v1/notifications/inbox" for route in app.routes):
        app.include_router(router, prefix="/api/v1")
    return TestClient(app, base_url="https://testserver"), recipient.id


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Synthetic-123"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_inbox_api_permissions_identity_isolation_and_replay(tmp_path: Path) -> None:
    client, recipient = _client(tmp_path)
    with client:
        admin, reviewer, other = (_headers(client, username) for username in ("admin", "reviewer", "other"))
        payload = {"recipient_id": recipient, "topic": "workflow.review_required", "resource_type": "approval", "resource_id": "APR-1", "idempotency_key": "publish-1"}
        assert client.get("/api/v1/notifications/inbox").status_code == 401
        assert client.post("/api/v1/notifications/inbox", headers=reviewer, json=payload).status_code == 403
        created = client.post("/api/v1/notifications/inbox", headers=admin, json=payload)
        assert created.status_code == 200, created.text
        notification = created.json()["notification"]
        assert created.json()["created"] is True
        replay = client.post("/api/v1/notifications/inbox", headers=admin, json=payload)
        assert replay.json() == {"notification": notification, "created": False}
        conflict = client.post("/api/v1/notifications/inbox", headers=admin, json={**payload, "resource_id": "APR-2"})
        assert conflict.status_code == 409
        assert client.get("/api/v1/notifications/inbox", headers=admin).json()["records"] == []
        assert client.get("/api/v1/notifications/inbox", headers=other).json()["records"] == []
        page = client.get("/api/v1/notifications/inbox", headers=reviewer).json()
        assert page["records"] == [notification] and page["unread_count"] == 1
        read_path = f"/api/v1/notifications/inbox/{notification['id']}/read"
        assert client.post(read_path, headers=other).status_code == 404
        assert client.post(read_path + "?workspace=sibling", headers=reviewer).status_code == 404
        read = client.post(read_path, headers=reviewer)
        assert read.status_code == 200 and read.json()["read_at"]
        assert client.post(read_path, headers=reviewer).json() == read.json()
        assert client.get("/api/v1/notifications/inbox?unread_only=true", headers=reviewer).json()["unread_count"] == 0
        assert client.get("/api/v1/notifications/inbox?limit=201", headers=reviewer).status_code == 422
        assert client.post("/api/v1/notifications/inbox", headers=admin, json={**payload, "topic": "financial.auto_approve"}).status_code == 422
        assert client.post("/api/v1/notifications/inbox", headers=admin, json={**payload, "resource_id": "https://untrusted.invalid"}).status_code == 400
        assert client.post("/api/v1/notifications/inbox", headers=admin, json={**payload, "raw_amount": "12"}).status_code == 422


def test_browser_inbox_ack_requires_csrf_and_exposes_canonical_workspaces(tmp_path: Path) -> None:
    client, recipient = _client(tmp_path)
    with client:
        admin = _headers(client, "admin")
        created = client.post("/api/v1/notifications/inbox", headers=admin, json={"recipient_id": recipient, "topic": "job.failed", "resource_type": "job", "resource_id": "JOB-1", "idempotency_key": "browser-1"})
        assert created.status_code == 200
        notification_id = created.json()["notification"]["id"]
        login = client.post("/api/v1/auth/browser/login", json={"username": "reviewer", "password": "Synthetic-123"})
        assert login.status_code == 200
        assert client.get("/api/v1/notifications/workspaces").json() == {"workspaces": ["default", "sibling"]}
        path = f"/api/v1/notifications/inbox/{notification_id}/read"
        assert client.post(path).status_code == 403
        read = client.post(path, headers={"X-ReconForge-CSRF": login.json()["csrf_token"]})
        assert read.status_code == 200 and read.json()["read_at"]
