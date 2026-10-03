"""Authentication middleware preserves the public API denial contract."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.errors import APIError
from reconforge.db import run_migrations


def _client(tmp_path: Path, *, web_root: Path | None = None) -> TestClient:
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    return TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://synthetic:unused@127.0.0.1:1/unused",
            postgres_require_tls=False,
            web_root=web_root,
        ),
        raise_server_exceptions=False,
    )


@pytest.mark.parametrize("transport", ["bearer", "browser_cookie"])
def test_missing_tenant_denial_keeps_status_request_id_and_security_headers(
    tmp_path: Path, transport: str,
) -> None:
    with _client(tmp_path) as client:
        headers = {"x-request-id": "synthetic-missing-tenant"}
        if transport == "bearer":
            headers["authorization"] = "Bearer synthetic-not-a-real-credential"
        else:
            headers["cookie"] = "__Host-reconforge_session=synthetic-not-a-real-credential"
        response = client.get("/api/v1/metrics/dashboard", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "tenant_required"
    assert response.json()["error"]["request_id"] == "synthetic-missing-tenant"
    assert response.headers["x-request-id"] == "synthetic-missing-tenant"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers
    assert "synthetic-not-a-real-credential" not in response.text


@pytest.mark.parametrize("path", ["/", "/live", "/assets/app.js"])
def test_hosted_spa_resources_load_with_session_cookie_without_tenant_header(
    tmp_path: Path, path: str,
) -> None:
    web_root = tmp_path / "dist"
    (web_root / "assets").mkdir(parents=True)
    (web_root / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    (web_root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    with _client(tmp_path, web_root=web_root) as client:
        response = client.get(path, headers={"cookie": "__Host-reconforge_session=synthetic"})
        missing = client.get("/assets/missing.js", headers={"cookie": "__Host-reconforge_session=synthetic"})
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert missing.status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/metrics/dashboard", "/api/v1/payables/suppliers"])
def test_hosted_spa_does_not_shadow_authenticated_business_routes(tmp_path: Path, path: str) -> None:
    db_path = tmp_path / "local.db"
    run_migrations(db_path)
    web_root = tmp_path / "dist"
    web_root.mkdir()
    (web_root / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    with TestClient(create_api_app(db_path, web_root=web_root)) as client:
        response = client.get(path)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("path", ["/api/v1/unknown", "/scim/v2/unknown"])
def test_unknown_api_paths_never_fall_back_to_spa_html(tmp_path: Path, path: str) -> None:
    web_root = tmp_path / "dist"
    web_root.mkdir()
    (web_root / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    with TestClient(create_api_app(tmp_path / "unused.db", web_root=web_root)) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("status,code", [(401, "invalid_token"), (403, "permission_denied"), (503, "identity_unavailable")])
def test_authentication_denial_stops_route_and_preserves_safe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, code: str,
) -> None:
    app_module = import_module("reconforge.api.app")

    def denied(*_args: object, **_kwargs: object) -> None:
        raise APIError(status_code=status, code=code, message="Synthetic access denied.")

    monkeypatch.setattr(app_module, "authenticate_server_request", denied)
    with _client(tmp_path) as client:
        response = client.get(
            "/api/v1/metrics/dashboard",
            headers={"authorization": "Bearer synthetic", "X-ReconForge-Tenant": "tenant-a"},
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert response.json()["error"]["message"] == "Synthetic access denied."
    assert response.headers["x-content-type-options"] == "nosniff"
