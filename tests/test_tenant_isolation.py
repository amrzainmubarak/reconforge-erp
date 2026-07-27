from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.security import create_session
from reconforge.auth import LocalAuthService
from reconforge.db import TenantDatabaseRouter, connect, run_migrations
from reconforge.db.tenancy import InvalidTenantIdError


def _tenant_db(root: Path, tenant_id: str, username: str) -> tuple[Path, str]:
    path = root / f"{tenant_id}.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    try:
        user = LocalAuthService(connection).init_admin(username=username, password="Secret-123")
        return path, create_session(connection, user=user).token
    finally:
        connection.close()


def test_database_per_tenant_api_requires_header_and_isolates_sessions(tmp_path: Path) -> None:
    root = tmp_path / "tenants"
    root.mkdir()
    _tenant_db(root, "tenant-a", "alice")
    _tenant_db(root, "tenant-b", "bob")

    a_connection = connect(root / "tenant-a.db", require_exists=True)
    try:
        alice = LocalAuthService(a_connection).users.get_by_username("alice")
        assert alice is not None
        alice_token = create_session(a_connection, user=alice).token
    finally:
        a_connection.close()
    b_connection = connect(root / "tenant-b.db", require_exists=True)
    try:
        bob = LocalAuthService(b_connection).users.get_by_username("bob")
        assert bob is not None
        bob_token = create_session(b_connection, user=bob).token
    finally:
        b_connection.close()

    client = TestClient(create_api_app(tmp_path / "control.db", tenant_db_root=root))
    no_scope = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {alice_token}"})
    assert no_scope.status_code == 400
    assert no_scope.json()["error"]["code"] == "tenant_required"

    alice_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {alice_token}", "X-ReconForge-Tenant": "tenant-a"},
    )
    assert alice_response.status_code == 200
    assert alice_response.json()["username"] == "alice"

    cross_tenant = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {alice_token}", "X-ReconForge-Tenant": "tenant-b"},
    )
    assert cross_tenant.status_code == 401
    assert cross_tenant.json()["error"]["code"] == "invalid_token"

    bob_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bob_token}", "X-ReconForge-Tenant": "tenant-b"},
    )
    assert bob_response.status_code == 200
    assert bob_response.json()["username"] == "bob"


def test_tenant_router_rejects_traversal_and_missing_database(tmp_path: Path) -> None:
    root = tmp_path / "tenants"
    root.mkdir()
    router = TenantDatabaseRouter.from_root(root)

    with pytest.raises(InvalidTenantIdError):
        router.path_for("../escape")
    with pytest.raises(InvalidTenantIdError):
        router.path_for("Tenant A")

    assert router.path_for("tenant-a", require_exists=False) == (root / "tenant-a.db").resolve()
