from __future__ import annotations

import os
import re
from types import SimpleNamespace

import pytest

from reconforge.infrastructure.postgres import (
    POSTGRES_RLS_SCHEMA_SQL,
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresConnectionPool,
    PostgresExecutionScope,
    PostgresSettings,
    PostgresTenantBoundary,
    PostgresUnavailableError,
    _hybrid_row_factory,
    _load_psycopg,
    install_postgres_rls_schema,
    normalize_scope_id,
    set_local_tenant_scope,
)


class _Transaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _Transaction:
        self.connection.events.append("begin")
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.connection.events.append("rollback" if exc_type else "commit")


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[str, ...] | None]] = []
        self.events: list[str] = []
        self.closed = False

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(self, sql: str, params: tuple[str, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        self.events.append("rollback-release")


def test_postgres_settings_reject_unsafe_configuration() -> None:
    with pytest.raises(PostgresConfigurationError):
        PostgresSettings(dsn=" ")
    with pytest.raises(PostgresConfigurationError):
        PostgresSettings(dsn="postgresql://db", statement_timeout_ms=0)


def test_postgres_settings_repr_does_not_expose_dsn() -> None:
    settings = PostgresSettings(dsn="postgresql://user:secret@db/reconforge")

    assert "secret" not in repr(settings)
    assert "postgresql://" not in repr(settings)


def test_scope_ids_reject_traversal_and_normalize_safe_ids() -> None:
    assert normalize_scope_id(" Tenant_A ") == "tenant_a"
    with pytest.raises(PostgresConfigurationError):
        normalize_scope_id("tenant/../other")


def test_tenant_scope_uses_parameterized_transaction_local_settings() -> None:
    connection = _FakeConnection()

    assert set_local_tenant_scope(
        connection,
        "Tenant_A",
        "Org_1",
        workspace_id="Workspace_1",
        legal_entity_id="Entity_1",
    ) == PostgresExecutionScope("tenant_a", "org_1", "workspace_1", "entity_1")
    assert connection.executed == [
        ("SELECT set_config('app.tenant_id', %s, true)", ("tenant_a",)),
        ("SELECT set_config('app.organization_id', %s, true)", ("org_1",)),
        ("SELECT set_config('app.workspace_id', %s, true)", ("workspace_1",)),
        ("SELECT set_config('app.legal_entity_id', %s, true)", ("entity_1",)),
        ("SELECT set_config('app.entity_id', %s, true)", ("entity_1",)),
    ]
    assert "tenant_a" not in connection.executed[0][0]


def test_execution_scope_rejects_orphan_or_unsafe_children() -> None:
    with pytest.raises(PostgresConfigurationError, match="requires organization_id"):
        PostgresExecutionScope("tenant-a", legal_entity_id="entity-a")
    with pytest.raises(PostgresConfigurationError, match="workspace_id"):
        PostgresExecutionScope("tenant-a", workspace_id="../workspace")


def test_tenant_boundary_scopes_and_closes_each_connection() -> None:
    connections: list[_FakeConnection] = []

    class _Factory:
        def connect(self) -> _FakeConnection:
            connection = _FakeConnection()
            connections.append(connection)
            return connection

    with PostgresTenantBoundary(_Factory()).transaction("tenant-a") as connection:
        connection.execute("SELECT 1")

    assert len(connections) == 1
    assert connections[0].events == ["begin", "commit"]
    assert connections[0].closed is True
    assert connections[0].executed[:5] == [
        ("SELECT set_config('app.tenant_id', %s, true)", ("tenant-a",)),
        ("SELECT set_config('app.organization_id', %s, true)", ("",)),
        ("SELECT set_config('app.workspace_id', %s, true)", ("",)),
        ("SELECT set_config('app.legal_entity_id', %s, true)", ("",)),
        ("SELECT set_config('app.entity_id', %s, true)", ("",)),
    ]


def test_tenant_boundary_rolls_back_and_closes_on_failure() -> None:
    connection = _FakeConnection()

    class _Factory:
        def connect(self) -> _FakeConnection:
            return connection

    with pytest.raises(RuntimeError, match="abort"), PostgresTenantBoundary(_Factory()).transaction("tenant-a"):
        raise RuntimeError("abort")

    assert connection.events == ["begin", "rollback"]
    assert connection.closed is True


def test_postgres_connection_pool_reuses_and_closes_bounded_connections() -> None:
    connections: list[_FakeConnection] = []

    class _Factory:
        def connect(self) -> _FakeConnection:
            connection = _FakeConnection()
            connections.append(connection)
            return connection

    pool = PostgresConnectionPool(_Factory(), max_size=1, acquire_timeout_seconds=0.1)
    first = pool.connect()
    first.close()
    second = pool.connect()
    second.close()

    assert len(connections) == 1
    assert connections[0].events == ["rollback-release", "rollback-release"]
    pool.close()
    assert connections[0].closed is True


def test_connection_factory_configures_tls_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_connect(dsn: str, **kwargs: object) -> object:
        calls.append((dsn, kwargs))
        return object()

    monkeypatch.setattr(
        "reconforge.infrastructure.postgres._load_psycopg",
        lambda: SimpleNamespace(connect=fake_connect),
    )

    PostgresConnectionFactory(
        PostgresSettings(
            dsn="postgresql://db/reconforge",
            application_name="test-suite",
            connect_timeout_seconds=7,
            statement_timeout_ms=1234,
        )
    ).connect()

    assert calls == [
        (
            "postgresql://db/reconforge",
            {
                "connect_timeout": 7,
                "application_name": "test-suite",
                "options": "-c statement_timeout=1234",
                "row_factory": _hybrid_row_factory,
                "sslmode": "verify-full",
            },
        )
    ]


def test_missing_driver_has_install_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_driver(name: str) -> SimpleNamespace:
        raise ImportError(name)

    monkeypatch.setattr("reconforge.infrastructure.postgres.importlib.import_module", missing_driver)
    with pytest.raises(PostgresUnavailableError, match="server"):
        _load_psycopg()


def test_rls_schema_is_explicit_and_idempotent_in_shape() -> None:
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_RLS_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_RLS_SCHEMA_SQL
    assert "current_setting('app.tenant_id', true)" in POSTGRES_RLS_SCHEMA_SQL
    assert "CREATE POLICY" in POSTGRES_RLS_SCHEMA_SQL

    connection = _FakeConnection()
    install_postgres_rls_schema(connection)
    assert connection.executed == [(POSTGRES_RLS_SCHEMA_SQL, None)]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_rls_hides_other_tenants() -> None:
    psycopg = pytest.importorskip("psycopg")

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_settings = PostgresSettings(dsn=dsn, require_tls=False)
    admin_settings = PostgresSettings(dsn=admin_dsn, require_tls=False)
    factory = PostgresConnectionFactory(app_settings)
    admin_factory = PostgresConnectionFactory(admin_settings)
    admin = admin_factory.connect()
    app = factory.connect()
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            if app_user:
                if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
                    pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, DELETE ON reconforge.tenants, reconforge.organizations, "
                    f"reconforge.tenant_memberships TO {app_user}"
                )

        role = app.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live RLS test requires a non-superuser, non-BYPASSRLS application role")

        tenant_a = "test_rls_a"
        tenant_b = "test_rls_b"
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            connection.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tenant_a, "A"))
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            connection.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tenant_b, "B"))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            rows = connection.execute("SELECT id FROM reconforge.tenants ORDER BY id").fetchall()
            assert [row[0] for row in rows] == [tenant_a]
    finally:
        for tenant_id in ("test_rls_a", "test_rls_b"):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id = %s", (tenant_id,))
            except psycopg.Error:
                pass
        app.close()
        admin.close()
