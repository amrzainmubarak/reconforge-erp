from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _client_with_users(tmp_path: Path) -> tuple[TestClient, Path]:
    db_path = tmp_path / "auth_api.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="disabled", password="Secret-123", role="reviewer")
        auth.disable_user(username="disabled")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path)), db_path


def test_login_me_and_logout_work(tmp_path: Path) -> None:
    client, _ = _client_with_users(tmp_path)

    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    token = login.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    after_logout = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert "password" not in me.text.lower()
    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    assert after_logout.status_code == 401


def test_login_fails_with_wrong_password_and_disabled_user(tmp_path: Path) -> None:
    client, _ = _client_with_users(tmp_path)

    wrong = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    disabled = client.post("/api/v1/auth/login", json={"username": "disabled", "password": "Secret-123"})

    assert wrong.status_code == 401
    assert disabled.status_code == 401
    assert "Traceback" not in wrong.text + disabled.text
    assert "Secret-123" not in disabled.text


def test_token_is_not_stored_plaintext(tmp_path: Path) -> None:
    client, db_path = _client_with_users(tmp_path)

    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    token = response.json()["access_token"]
    connection = connect(db_path, require_exists=True)
    try:
        rows = connection.execute("SELECT token_hash FROM api_sessions").fetchall()
    finally:
        connection.close()

    assert response.status_code == 200
    assert rows
    assert all(row["token_hash"] != token for row in rows)
    assert token not in str([row["token_hash"] for row in rows])
