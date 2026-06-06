from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _setup(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "users_api.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path))


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_admin_can_list_create_patch_disable_and_manage_user_roles(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    admin_headers = {"Authorization": f"Bearer {_token(client, 'admin')}"}

    listed = client.get("/api/v1/users", headers=admin_headers)
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"username": "preparer", "password": "New-Secret-123", "role": "preparer"},
    )
    patched = client.patch(
        "/api/v1/users/preparer",
        headers=admin_headers,
        json={"display_name": "Local Preparer"},
    )
    assigned = client.post("/api/v1/users/preparer/roles", headers=admin_headers, json={"role": "reviewer"})
    removed = client.delete("/api/v1/users/preparer/roles/reviewer", headers=admin_headers)
    permissions = client.get("/api/v1/users/preparer/permissions", headers=admin_headers)
    disabled = client.post("/api/v1/users/preparer/disable", headers=admin_headers)

    assert listed.status_code == 200
    assert created.status_code == 200
    assert patched.json()["user"]["display_name"] == "Local Preparer"
    assert assigned.status_code == 200
    assert "reviewer" in assigned.json()["roles"]
    assert removed.status_code == 200
    assert permissions.status_code == 200
    assert "reconciliation.prepare" in permissions.json()["permissions"]
    assert disabled.status_code == 200
    assert disabled.json()["user"]["disabled"] is True
    combined = listed.text + created.text + patched.text + disabled.text
    assert "password_hash" not in combined
    assert "password_salt" not in combined
    assert "New-Secret-123" not in combined


def test_unauthorized_user_lacks_users_manage(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    reviewer_headers = {"Authorization": f"Bearer {_token(client, 'reviewer')}"}

    response = client.post(
        "/api/v1/users",
        headers=reviewer_headers,
        json={"username": "other", "password": "Secret-123", "role": "reviewer"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert "Traceback" not in response.text


def test_roles_endpoints_work_without_secret_material(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    headers = {"Authorization": f"Bearer {_token(client, 'admin')}"}

    roles = client.get("/api/v1/roles", headers=headers)
    permissions = client.get("/api/v1/roles/reviewer/permissions", headers=headers)

    assert roles.status_code == 200
    assert "reviewer" in {role["name"] for role in roles.json()["roles"]}
    assert permissions.status_code == 200
    assert "audit.read" in permissions.json()["permissions"]
    assert "password" not in roles.text.lower() + permissions.text.lower()
