from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.browser_session import BROWSER_CSRF_HEADER, BROWSER_SESSION_COOKIE, issue_browser_csrf_token
from reconforge.api.dependencies import get_current_user
from reconforge.api.server_identity import AuthenticatedServerRequest
from reconforge.auth.models import LocalUser
from reconforge.platform.common import current_server_principal


def test_server_cookie_principal_reaches_sync_route_and_retains_csrf_guard(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The server-profile middleware must bind cookie principals before sync endpoints run."""

    import reconforge.api.app as app_module

    user = LocalUser(id="cookie-user", username="cookie-admin", display_name="Cookie Administrator")

    def authenticate(_request: Any, token: str) -> AuthenticatedServerRequest | None:
        if token != "synthetic-cookie-token":
            return None
        return AuthenticatedServerRequest(
            user=user,
            permissions=frozenset({"audit.read"}),
            principal_type="user",
            session_id="cookie-session",
        )

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    root = tmp_path / "tenants"
    root.mkdir()
    app = create_api_app(
        tmp_path / "control.db",
        tenant_db_root=root,
        postgres_dsn="postgresql://identity.invalid/reconforge",
        postgres_require_tls=False,
    )

    @app.post("/api/v1/test-cookie-principal")
    def probe(_current_user: LocalUser = Depends(get_current_user)) -> dict[str, object]:
        principal = current_server_principal()
        return {
            "username": _current_user.username,
            "principal_bound": principal is not None,
            "principal_type": principal.principal_type if principal is not None else None,
        }

    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(BROWSER_SESSION_COOKIE, "synthetic-cookie-token")
    headers = {"X-ReconForge-Tenant": "tenant-a"}

    missing_csrf = client.post("/api/v1/test-cookie-principal", headers=headers)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_required"

    response = client.post(
        "/api/v1/test-cookie-principal",
        headers={
            **headers,
            BROWSER_CSRF_HEADER: issue_browser_csrf_token("synthetic-cookie-token"),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "username": "cookie-admin",
        "principal_bound": True,
        "principal_type": "user",
    }
