"""Contract tests for the authenticated PostgreSQL scoped-export API."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.application.scoped_exports import (
    ScopedExportDataset,
    ScopedExportScope,
    ScopedExportSnapshot,
)
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations


def test_scoped_export_boundary_is_server_only_and_has_no_sqlite_fallback(tmp_path: Path) -> None:
    import reconforge.api.server_scoped_exports as export_boundary

    app = create_api_app(tmp_path / "local.db")
    request = SimpleNamespace(app=app)

    with pytest.raises(APIError) as raised:
        export_boundary.execute_postgres_scoped_export(request, lambda _repository, _scope: None)

    assert raised.value.status_code == 501
    assert raised.value.code == "scoped_export_server_only"


def test_scoped_export_route_is_authenticated_hierarchy_bound_and_deterministic(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.scoped_exports as export_routes
    import reconforge.api.server_scoped_exports as export_boundary

    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    permissions = frozenset({"reports.read"})
    expected_scope = ScopedExportScope(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        organization_id="org-a",
        entity_id="entity-a",
    )
    observed_permissions: list[dict[str, object]] = []

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "server-token" else None

    class FakeRepository:
        def snapshot(self, scope: ScopedExportScope) -> ScopedExportSnapshot:
            assert scope == expected_scope
            return ScopedExportSnapshot(
                scope=scope,
                datasets=(
                    ScopedExportDataset(
                        name="organizations",
                        rows=({"id": "org-a", "workspace_id": "workspace-a"},),
                    ),
                ),
            )

    def execute(request: Any, operation: Any) -> dict[str, object]:
        assert request_tenant_id(request) == "tenant-a"
        return operation(FakeRepository(), expected_scope)

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(export_routes, "request_execution_scope", lambda _request: RequestExecutionScope(
        "tenant-a", "workspace-a", "org-a", "entity-a"
    ))
    monkeypatch.setattr(export_boundary, "request_execution_scope", lambda _request: RequestExecutionScope(
        "tenant-a", "workspace-a", "org-a", "entity-a"
    ))
    monkeypatch.setattr(
        export_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: observed_permissions.append(kwargs),
    )
    monkeypatch.setattr(export_routes, "server_scoped_exports_enabled", lambda _request: True)
    monkeypatch.setattr(export_routes, "execute_postgres_scoped_export", execute)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    run_migrations(tenant_root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://exports.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"scoped-export-cursor-test-key-32-bytes",
        )
    )
    headers = {
        "X-ReconForge-Tenant": "tenant-a",
        "X-ReconForge-Workspace": "workspace-a",
        "X-ReconForge-Organization": "org-a",
        "X-ReconForge-Legal-Entity": "entity-a",
        "Authorization": "Bearer server-token",
    }

    response = client.get("/api/v1/exports/scoped", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["digest"] == body["export"]["artifact_digest"]
    assert len(body["digest"]) == hashlib.sha256(b"").digest_size * 2
    assert body["byte_size"] > 0
    assert body["source"] == {
        "kind": "postgresql-scoped-control-plane-export",
        "server_mode": True,
    }
    assert body["export"]["scope"] == {
        "entity_id": "entity-a",
        "organization_id": "org-a",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
    }
    assert observed_permissions == [
        {
            "permission": "reports.read",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "entity_id": "entity-a",
        }
    ]
