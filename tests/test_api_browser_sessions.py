from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.browser_session import BROWSER_CSRF_HEADER, BROWSER_SESSION_COOKIE
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "browser_session.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path), base_url="https://testserver")


def test_browser_login_uses_secure_httponly_cookie_and_never_serializes_bearer(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/v1/auth/browser/login", json={"username": "admin", "password": "Secret-123"})
    me = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert set(response.json()) == {"csrf_token", "expires_at"}
    assert "access_token" not in response.text
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{BROWSER_SESSION_COOKIE.lower()}=" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=strict" in set_cookie
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_browser_cookie_rejects_unsafe_request_without_bound_csrf_proof(tmp_path: Path) -> None:
    client = _client(tmp_path)
    login = client.post("/api/v1/auth/browser/login", json={"username": "admin", "password": "Secret-123"})

    missing = client.post("/api/v1/auth/logout")
    malformed = client.post("/api/v1/auth/logout", headers={BROWSER_CSRF_HEADER: "not-a-proof"})
    valid = client.post("/api/v1/auth/logout", headers={BROWSER_CSRF_HEADER: login.json()["csrf_token"]})
    after_logout = client.get("/api/v1/auth/me")

    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_required"
    assert malformed.status_code == 403
    assert malformed.json()["error"]["code"] == "csrf_required"
    assert valid.status_code == 200
    assert valid.json()["revoked"] is True
    assert BROWSER_SESSION_COOKIE not in valid.headers.get("set-cookie", "") or "max-age=0" in valid.headers.get("set-cookie", "").lower()
    assert after_logout.status_code == 401


def test_browser_csrf_proof_cannot_be_replayed_by_a_different_session(tmp_path: Path) -> None:
    first = _client(tmp_path / "first")
    second = _client(tmp_path / "second")
    first_login = first.post("/api/v1/auth/browser/login", json={"username": "admin", "password": "Secret-123"})
    second_login = second.post("/api/v1/auth/browser/login", json={"username": "admin", "password": "Secret-123"})

    replay = second.post("/api/v1/auth/logout", headers={BROWSER_CSRF_HEADER: first_login.json()["csrf_token"]})
    valid = second.post("/api/v1/auth/logout", headers={BROWSER_CSRF_HEADER: second_login.json()["csrf_token"]})

    assert replay.status_code == 403
    assert replay.json()["error"]["code"] == "csrf_required"
    assert valid.status_code == 200


def test_browser_login_invalid_credentials_do_not_set_cookie_or_echo_password(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/v1/auth/browser/login", json={"username": "admin", "password": "wrong-password"})

    assert response.status_code == 401
    assert BROWSER_SESSION_COOKIE not in response.headers.get("set-cookie", "")
    assert "wrong-password" not in response.text


def test_browser_session_docs_and_package_manifest_preserve_the_boundary() -> None:
    adr = Path("docs/adr/0199-browser-administration-sessions-are-same-origin-and-csrf-bound.md").read_text(
        encoding="utf-8"
    )
    runbook = Path("docs/operations/browser-administration-sessions.md").read_text(encoding="utf-8")
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")

    assert "__Host-reconforge_session" in adr
    assert "X-ReconForge-CSRF" in adr
    assert "HttpOnly" in runbook and "SameSite=Strict" in runbook
    assert "include docs/adr/0199-browser-administration-sessions-are-same-origin-and-csrf-bound.md" in manifest
    assert "include docs/operations/browser-administration-sessions.md" in manifest
