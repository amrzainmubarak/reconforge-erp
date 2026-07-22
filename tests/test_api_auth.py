from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _client_with_users(tmp_path: Path, *, admin_username: str = "admin", create_aux_user: bool = False) -> tuple[TestClient, Path, str]:
    db_path = tmp_path / "auth_api.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username=admin_username, password="Secret-123")
        auth.create_user(username="disabled", password="Secret-123", role="reviewer")
        auth.disable_user(username="disabled")
        if create_aux_user:
            auth.create_user(username=f"{admin_username}-alt", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path)), db_path, admin_username


def test_login_me_and_logout_work(tmp_path: Path) -> None:
    client, _, admin_username = _client_with_users(tmp_path)

    login = client.post("/api/v1/auth/login", json={"username": admin_username, "password": "Secret-123"})
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
    client, _, admin_username = _client_with_users(tmp_path)

    wrong = client.post("/api/v1/auth/login", json={"username": admin_username, "password": "wrong"})
    disabled = client.post("/api/v1/auth/login", json={"username": "disabled", "password": "Secret-123"})

    assert wrong.status_code == 401
    assert disabled.status_code == 401
    assert "Traceback" not in wrong.text + disabled.text
    assert "Secret-123" not in disabled.text


def test_token_is_not_stored_plaintext(tmp_path: Path) -> None:
    client, db_path, admin_username = _client_with_users(tmp_path)

    response = client.post("/api/v1/auth/login", json={"username": admin_username, "password": "Secret-123"})
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


def test_authentication_throttles_session_last_used_writes(tmp_path: Path) -> None:
    client, db_path, admin_username = _client_with_users(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": admin_username, "password": "Secret-123"})
    token = login.json()["access_token"]
    recent = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    connection = connect(db_path, require_exists=True)
    try:
        connection.execute("UPDATE api_sessions SET last_used_at = ?", (recent,))
        connection.commit()
    finally:
        connection.close()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    connection = connect(db_path, require_exists=True)
    try:
        unchanged = str(connection.execute("SELECT last_used_at FROM api_sessions").fetchone()[0])
        stale = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        connection.execute("UPDATE api_sessions SET last_used_at = ?", (stale,))
        connection.commit()
    finally:
        connection.close()

    refreshed_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    connection = connect(db_path, require_exists=True)
    try:
        refreshed = str(connection.execute("SELECT last_used_at FROM api_sessions").fetchone()[0])
    finally:
        connection.close()

    assert response.status_code == 200
    assert unchanged == recent
    assert refreshed_response.status_code == 200
    assert refreshed > stale


def test_login_rate_limit_blocks_excessive_failures(tmp_path: Path) -> None:
    client, _, admin_username = _client_with_users(tmp_path, create_aux_user=True)
    payload = {"username": f"{admin_username}-alt", "password": "wrong-password"}
    last_status = 0
    for _ in range(8):
        response = client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 401
        last_status = response.status_code
    blocked = client.post("/api/v1/auth/login", json=payload)
    assert last_status == 401
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "login_rate_limited"


def test_login_rate_limit_clears_on_success(tmp_path: Path) -> None:
    client, _, admin_username = _client_with_users(tmp_path, create_aux_user=True)
    bad_payload = {"username": f"{admin_username}-alt", "password": "wrong-password"}
    for _ in range(4):
        assert client.post("/api/v1/auth/login", json=bad_payload).status_code == 401

    good_payload = {"username": f"{admin_username}-alt", "password": "Secret-123"}
    success = client.post("/api/v1/auth/login", json=good_payload)
    assert success.status_code == 200
    assert success.json()["token_type"] == "bearer"

    blocked = client.post("/api/v1/auth/login", json=bad_payload)
    assert blocked.status_code == 401
    assert blocked.json()["error"]["code"] == "invalid_credentials"
