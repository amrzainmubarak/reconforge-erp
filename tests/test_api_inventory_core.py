from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import Request

from reconforge.api import create_api_app
from reconforge.api.dependencies import get_db
from reconforge.api.errors import APIError
from reconforge.api.routes.inventory_core import get_inventory_local_db, router
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

    assert route_dependencies.count(get_inventory_local_db) == len(router.routes)
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
