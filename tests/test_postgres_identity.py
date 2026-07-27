"""Security contracts and optional live tests for PostgreSQL identity."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import (
    POSTGRES_IDENTITY_SCHEMA_SQL,
    PostgresIdentityError,
    PostgresIdentityRepository,
    PostgresIdentityValidationError,
)


class _Cursor:
    def __init__(self, row: tuple[Any, ...] | None = None, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.user_row = (
            "user-a",
            "alice",
            "Alice",
            "alice@example.test",
            "hash",
            "salt",
            390000,
            "pbkdf2_sha256",
            False,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            0,
            None,
            "tenant_a",
        )

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "select id from reconforge.identity_roles" in normalized:
            return _Cursor(row=("role-admin",))
        if "from reconforge.identity_users" in normalized:
            return _Cursor(row=self.user_row)
        if "returning tenant_id, id, name, description" in normalized:
            return _Cursor(row=("tenant_a", "role-admin", "admin", "", "created", "updated"))
        if "returning id, username, display_name" in normalized:
            return _Cursor(row=self.user_row)
        if "select token_hash" in normalized:
            return _Cursor(row=None)
        return _Cursor()


def test_identity_schema_is_tenant_scoped_and_does_not_store_raw_tokens() -> None:
    assert "password_hash TEXT NOT NULL" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "token_hash TEXT NOT NULL" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "identity_sessions" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "failed_login_count" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_IDENTITY_SCHEMA_SQL
    assert "UNIQUE (tenant_id, username)" in POSTGRES_IDENTITY_SCHEMA_SQL


def test_identity_role_creation_parameterizes_scope_and_session_hashes_token() -> None:
    connection = _FakeConnection()
    repository = PostgresIdentityRepository(connection)
    role = repository.create_role(tenant_id="TENANT_A", role_name="Admin")
    session = repository.create_session(tenant_id="tenant_a", user_id="user-a")

    assert role["name"] == "admin"
    assert session.token
    assert session.token not in " ".join(sql for sql, _ in connection.executed)
    assert any(
        params is not None and session.token not in params and hashlib.sha256(session.token.encode()).hexdigest() in params
        for _, params in connection.executed
    )
    assert all(session.token not in str(params) for _, params in connection.executed)


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("get_user", {"tenant_id": "../tenant", "username": "alice"}),
        ("create_session", {"tenant_id": "tenant_a", "user_id": "../user"}),
        ("create_role", {"tenant_id": "tenant_a", "role_name": "Not A Role"}),
        ("create_permission", {"tenant_id": "tenant_a", "permission_name": "bad permission"}),
    ],
)
def test_identity_rejects_unsafe_scope_and_names(method: str, kwargs: dict[str, object]) -> None:
    repository = PostgresIdentityRepository(_FakeConnection())
    with pytest.raises(PostgresIdentityValidationError):
        getattr(repository, method)(**kwargs)


def test_identity_user_creation_requires_existing_role() -> None:
    class _NoRoleConnection(_FakeConnection):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
            self.executed.append((sql, params))
            if "select id from reconforge.identity_roles" in " ".join(sql.split()).lower():
                return _Cursor(row=None)
            return _Cursor()

    repository = PostgresIdentityRepository(_NoRoleConnection())
    with pytest.raises(PostgresIdentityError):
        repository.create_user(
            tenant_id="tenant_a",
            user_id="user-a",
            username="alice",
            password="Strong-password-123",
            role_name="admin",
        )


def test_identity_user_row_maps_locked_until_before_tenant_id() -> None:
    connection = _FakeConnection()
    repository = PostgresIdentityRepository(connection)

    user = repository.get_user(tenant_id="tenant_a", username="alice")

    assert user is not None
    assert user.locked_until is None
    assert user.created_at == "2026-01-01T00:00:00Z"


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_identity_is_tenant_isolated_and_revocable() -> None:
    psycopg = pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import install_postgres_rls_schema

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    app = factory.connect()
    tenant_a = "identity_a"
    tenant_b = "identity_b"
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                    f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                    f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                    f"reconforge.identity_sessions TO {app_user}"
                )
        role = app.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live identity test requires a non-superuser, non-BYPASSRLS application role")

        for tenant_id, name in ((tenant_a, "Identity A"), (tenant_b, "Identity B")):
            with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                connection.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, name),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresIdentityRepository(connection)
            repository.create_role(tenant_id=tenant_a, role_name="Admin")
            repository.create_permission(tenant_id=tenant_a, permission_name="ledger.post")
            repository.grant_permission(tenant_id=tenant_a, role_name="admin", permission_name="ledger.post")
            user = repository.create_user(
                tenant_id=tenant_a,
                user_id="user-a",
                username="Alice",
                password="Strong-password-123",
                role_name="admin",
                email="alice@example.test",
            )
            assert user.username == "alice"
            assert repository.user_has_permission(
                tenant_id=tenant_a, user_id="user-a", permission_name="ledger.post"
            )
            assert repository.authenticate_user(
                tenant_id=tenant_a, username="alice", password="Strong-password-123"
            ) is not None
            assert repository.authenticate_user(tenant_id=tenant_a, username="alice", password="wrong") is None
            session = repository.create_session(tenant_id=tenant_a, user_id="user-a")
            assert repository.authenticate_token(tenant_id=tenant_a, token=session.token) is not None
            stored_hash = connection.execute(
                "SELECT token_hash FROM reconforge.identity_sessions WHERE tenant_id = %s AND id = %s",
                (tenant_a, session.id),
            ).fetchone()[0]
            assert stored_hash == hashlib.sha256(session.token.encode()).hexdigest()
            assert stored_hash != session.token
            assert repository.revoke_token(tenant_id=tenant_a, token=session.token)
            assert repository.authenticate_token(tenant_id=tenant_a, token=session.token) is None
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresIdentityRepository(connection)
            assert repository.get_user(tenant_id=tenant_b, username="alice") is None
            assert repository.authenticate_token(tenant_id=tenant_b, token=session.token) is None
    finally:
        for tenant_id in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id = %s", (tenant_id,))
            except psycopg.Error:
                pass
        app.close()
        admin.close()
