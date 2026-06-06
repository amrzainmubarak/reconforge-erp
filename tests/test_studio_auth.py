from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import DatabaseError, connect, run_migrations
from reconforge.studio.app import STUDIO_SESSION_COOKIE, create_studio_app

PASSWORD = "Secret-123"
runner = CliRunner()


def _auth_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "studio_auth.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        service.init_admin(username="admin", password=PASSWORD)
        service.create_user(username="reviewer", password=PASSWORD, role="reviewer")
        service.create_user(username="preparer", password=PASSWORD, role="preparer")
        service.create_user(username="disabled", password=PASSWORD, role="reviewer")
        service.disable_user(username="disabled")
    finally:
        connection.close()
    return db_path


def _csrf_for_action(html: str, action: str) -> str:
    pattern = rf'<form[^>]+action="{re.escape(action)}".*?name="csrf_token" value="([^"]+)"'
    match = re.search(pattern, html, flags=re.DOTALL)
    assert match is not None
    return match.group(1)


def _login(client: TestClient, username: str = "reviewer", password: str = PASSWORD) -> str:
    login_page = client.get("/login")
    csrf = _csrf_for_action(login_page.text, "/login")
    response = client.post(
        "/login",
        data={"csrf_token": csrf, "username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie = response.cookies.get(STUDIO_SESSION_COOKIE)
    assert cookie
    return cookie


def test_studio_trusted_local_mode_still_works_without_auth(tmp_path: Path) -> None:
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert "ReconForge Studio" in response.text


def test_studio_auth_required_mode_requires_db(tmp_path: Path) -> None:
    with pytest.raises(DatabaseError, match="needs --db"):
        create_studio_app("examples/sample_data", tmp_path, require_auth=True)


def test_studio_cli_require_auth_requires_existing_database(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "studio",
            "--input",
            "examples/sample_data",
            "--output",
            str(tmp_path),
            "--require-auth",
            "--db",
            str(tmp_path / "missing.db"),
        ],
    )

    assert result.exit_code == 1
    assert "ReconForge database not found" in result.output


def test_studio_auth_required_mode_redirects_until_valid_login(tmp_path: Path) -> None:
    db_path = _auth_db(tmp_path)
    client = TestClient(create_studio_app("examples/sample_data", tmp_path, require_auth=True, db_path=db_path))

    before_login = client.get("/", follow_redirects=False)
    cookie = _login(client, username="reviewer")
    after_login = client.get("/")

    connection = connect(db_path, require_exists=True)
    try:
        rows = connection.execute("SELECT token_hash FROM api_sessions").fetchall()
    finally:
        connection.close()

    assert before_login.status_code == 303
    assert before_login.headers["location"] == "/login"
    assert after_login.status_code == 200
    assert "ReconForge Studio" in after_login.text
    assert rows
    assert all(row["token_hash"] != cookie for row in rows)
    assert cookie not in after_login.text
    assert PASSWORD not in after_login.text
    assert "password_hash" not in after_login.text
    assert "token_hash" not in after_login.text


def test_studio_auth_invalid_and_disabled_login_fail_safely(tmp_path: Path) -> None:
    db_path = _auth_db(tmp_path)
    client = TestClient(create_studio_app("examples/sample_data", tmp_path, require_auth=True, db_path=db_path))
    login_page = client.get("/login")
    csrf = _csrf_for_action(login_page.text, "/login")

    wrong = client.post(
        "/login",
        data={"csrf_token": csrf, "username": "reviewer", "password": "wrong"},
    )
    disabled = client.post(
        "/login",
        data={"csrf_token": csrf, "username": "disabled", "password": PASSWORD},
    )

    body = wrong.text + disabled.text
    assert wrong.status_code == 401
    assert disabled.status_code == 401
    assert "Invalid username or password." in body
    assert "Traceback" not in body
    assert PASSWORD not in body
    assert "password_hash" not in body
    assert "token_hash" not in body


def test_studio_logout_revokes_session_cookie(tmp_path: Path) -> None:
    db_path = _auth_db(tmp_path)
    client = TestClient(create_studio_app("examples/sample_data", tmp_path, require_auth=True, db_path=db_path))
    _login(client)

    logout_page = client.get("/logout")
    csrf = _csrf_for_action(logout_page.text, "/logout")
    logout = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    after_logout = client.get("/", follow_redirects=False)

    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert after_logout.status_code == 303
    assert after_logout.headers["location"] == "/login"


def test_studio_review_update_requires_rbac_permission(tmp_path: Path) -> None:
    db_path = _auth_db(tmp_path)
    client = TestClient(create_studio_app("examples/sample_data", tmp_path, require_auth=True, db_path=db_path))
    _login(client, username="preparer")
    exceptions_page = client.get("/exceptions")
    csrf = _csrf_for_action(exceptions_page.text, "/exceptions/update-review")

    response = client.post(
        "/exceptions/update-review",
        data={
            "csrf_token": csrf,
            "exception_id": "EXC-0001",
            "status": "Under Review",
            "reviewer": "Preparer",
        },
    )

    assert response.status_code == 403
    assert "Permission Denied" in response.text
    assert "Traceback" not in response.text
    assert not (tmp_path / "review_state.json").exists()


def test_studio_review_update_succeeds_for_reviewer_role(tmp_path: Path) -> None:
    db_path = _auth_db(tmp_path)
    client = TestClient(create_studio_app("examples/sample_data", tmp_path, require_auth=True, db_path=db_path))
    _login(client, username="reviewer")
    exceptions_page = client.get("/exceptions")
    csrf = _csrf_for_action(exceptions_page.text, "/exceptions/update-review")

    response = client.post(
        "/exceptions/update-review",
        data={
            "csrf_token": csrf,
            "exception_id": "EXC-0001",
            "status": "Under Review",
            "reviewer": "Reviewer",
        },
    )

    assert response.status_code == 200
    assert "Review updated for EXC-0001 as Under Review." in response.text
    assert (tmp_path / "review_state.json").exists()
