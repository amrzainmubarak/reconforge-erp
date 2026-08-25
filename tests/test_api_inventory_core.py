from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.dependencies import get_db, get_local_db
from reconforge.api.errors import APIError
from reconforge.api.routes.inventory_core import get_inventory_local_db, router
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.application.inventory_core import InventoryCoreSummary
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations


def _request(app: object) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/inventory/summary",
            "headers": [],
            "app": app,
        }
    )


def test_inventory_router_uses_the_explicit_local_database_boundary() -> None:
    route_dependencies: list[object] = []
    pending = [dependency for route in router.routes for dependency in route.dependant.dependencies]
    while pending:
        dependency = pending.pop()
        route_dependencies.append(dependency.call)
        pending.extend(dependency.dependencies)

    assert route_dependencies.count(get_local_db) == len(router.routes)
    assert get_inventory_local_db not in route_dependencies
    assert get_db not in route_dependencies


def test_inventory_local_database_fails_closed_in_postgres_server_profile(tmp_path: Path) -> None:
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tenant_root,
        postgres_dsn="postgresql://synthetic.invalid/reconforge",
        postgres_require_tls=False,
    )

    generator = get_inventory_local_db(_request(app))
    with pytest.raises(APIError) as error:
        next(generator)
    generator.close()

    assert error.value.status_code == 501
    assert error.value.code == "inventory_server_backend_unavailable"


def test_inventory_local_database_remains_available_in_local_profile(tmp_path: Path) -> None:
    database = tmp_path / "inventory.db"
    run_migrations(database)
    app = create_api_app(database)

    generator = get_inventory_local_db(_request(app))
    connection = next(generator)
    try:
        assert isinstance(connection, sqlite3.Connection)
    finally:
        generator.close()
        connection.close()


def test_server_inventory_routes_bind_scope_and_use_postgres_adapter(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.inventory_core as inventory_routes
    from reconforge.api.server_inventory_core import InventoryExecutionScope

    user = LocalUser(id="inventory-user", username="inventory-user", display_name="Inventory User")
    permissions = frozenset({"inventory.read", "inventory.manage", "inventory.post"})
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeRepository:
        def upsert_uom(self, **values: object) -> dict[str, object]:
            calls.append(("upsert_uom", values))
            return {"uom_code": values["uom_code"], "workspace_id": values["workspace"]}

        def summary(self, **values: object) -> InventoryCoreSummary:
            calls.append(("summary", values))
            return InventoryCoreSummary(str(values["workspace"]), 1, 0, 0, 0, 0, 0, 0, 0)

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "inventory-token" else None

    def execute(request: Any, operation: Any, **kwargs: object) -> Any:
        assert request_tenant_id(request) == "tenant-a"
        return operation(
            FakeRepository(),
            InventoryExecutionScope(
                RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
                organization_code="ORG",
                entity_code="ENTITY",
            ),
        )

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)
    monkeypatch.setattr(
        inventory_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
    )
    monkeypatch.setattr(inventory_routes, "enforce_server_scoped_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inventory_routes, "enforce_server_scoped_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inventory_routes, "execute_postgres_inventory", execute)

    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tmp_path / "tenants",
            postgres_dsn="postgresql://inventory.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {
        "X-ReconForge-Tenant": "tenant-a",
        "X-ReconForge-Workspace": "workspace-a",
        "Authorization": "Bearer inventory-token",
    }
    saved = client.post(
        "/api/v1/inventory/units",
        headers=headers,
        json={"uom_code": "EA", "name": "Each", "workspace": "spoofed-workspace"},
    )
    summarized = client.get("/api/v1/inventory/summary", headers=headers)

    assert saved.status_code == 200, saved.text
    assert summarized.status_code == 200, summarized.text
    assert next(values for name, values in calls if name == "upsert_uom")["workspace"] == "workspace-a"
    assert next(values for name, values in calls if name == "summary")["workspace"] == "workspace-a"
