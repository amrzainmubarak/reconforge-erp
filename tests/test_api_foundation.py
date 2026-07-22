from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge import __version__
from reconforge.api import create_api_app
from reconforge.cli import app
from reconforge.db import run_migrations

runner = CliRunner()


def test_api_health_and_version_work_without_auth(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    run_migrations(db_path)
    client = TestClient(create_api_app(db_path))

    health = client.get("/api/v1/health")
    version = client.get("/api/v1/version")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"] == __version__
    assert health.json()["database"]["reachable"] is True
    assert health.json()["database"]["schema_version"] == 12
    assert health.json()["database"]["path_summary"] == "api.db"
    assert version.status_code == 200
    assert version.json()["scope"] == "local/self-hosted foundation"


def test_protected_route_requires_auth_and_returns_structured_error(tmp_path: Path) -> None:
    db_path = tmp_path / "protected.db"
    run_migrations(db_path)
    client = TestClient(create_api_app(db_path))

    response = client.get("/api/v1/users")

    assert response.status_code == 401
    payload = response.json()
    assert set(payload["error"]) == {"code", "message", "request_id"}
    assert payload["error"]["code"] == "auth_required"
    assert "Traceback" not in response.text


def test_api_serve_missing_db_fails_without_starting_server(tmp_path: Path) -> None:
    result = runner.invoke(app, ["api", "serve", "--db", str(tmp_path / "missing.db")])

    assert result.exit_code == 1
    assert "Run 'reconforge db init' first" in result.output
    assert "Traceback" not in result.output
