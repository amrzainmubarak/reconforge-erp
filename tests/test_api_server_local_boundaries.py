"""Server-profile contracts for local-only routes that are intentionally fail-closed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest
from reconforge.auth.models import LocalUser


def test_sqlite_only_exceptions_and_workflow_routes_fail_closed_in_server_profile(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies

    user = LocalUser(id="server-user", username="server-user", display_name="Server User")

    def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
        if credential != "server-token":
            return None
        return AuthenticatedServerRequest(
            user=user,
            permissions=frozenset({"db.read", "exceptions.read", "exceptions.manage"}),
            principal_type="user",
        )

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)

    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn="postgresql://unreachable.invalid/reconforge",
        postgres_require_tls=False,
    )
    headers = {
        "X-ReconForge-Tenant": "tenant-a",
        "Authorization": "Bearer server-token",
    }
    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/exceptions", headers=headers),
            client.post("/api/v1/exceptions/EXC-1/assign", headers=headers, json={"owner": "reviewer"}),
            client.post("/api/v1/exceptions/EXC-1/status", headers=headers, json={"status": "Closed"}),
            client.get("/api/v1/workflow/transitions", headers=headers, params={"object_type": "reconciliation"}),
            client.post(
                "/api/v1/workflow/objects",
                headers=headers,
                json={"object_type": "reconciliation", "object_id": "REC-1", "status": "Draft"},
            ),
            client.get("/api/v1/workflow/objects/reconciliation/REC-1", headers=headers),
            client.get("/api/v1/workflow/objects/reconciliation/REC-1/history", headers=headers),
        ]

    assert [response.status_code for response in responses] == [501] * len(responses)
    assert {response.json()["error"]["code"] for response in responses[:3]} == {
        "exceptions_server_backend_unavailable"
    }
    assert {response.json()["error"]["code"] for response in responses[3:]} == {
        "workflow_server_backend_unavailable"
    }
