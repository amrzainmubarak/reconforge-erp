from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import (
    POSTGRES_RLS_SCHEMA_SQL,
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresConnectionPool,
    PostgresConnectionPoolClosedError,
    PostgresConnectionPoolSnapshot,
    PostgresExecutionScope,
    PostgresPooledConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    PostgresUnavailableError,
    _hybrid_row_factory,
    _load_psycopg,
    install_postgres_rls_schema,
    normalize_scope_id,
    set_local_tenant_scope,
)
from tests.postgres_test_hygiene import (
    PAYABLES_TENANT_CLEANUP_PLAN,
    RECEIVABLES_TENANT_CLEANUP_PLAN,
    RLS_TENANT_CLEANUP_PLAN,
    cleanup_postgres_test_tenants_as_admin,
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


class _CleanupCursor:
    def __init__(self, *, row: tuple[object, ...] | None = None, rows: list[tuple[object, ...]] | None = None) -> None:
        self._row = row
        self._rows = [] if rows is None else rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _CleanupTransaction:
    def __init__(self, connection: _CleanupAdminConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _CleanupTransaction:
        self.connection.events.append("begin")
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.connection.events.append("rollback" if exc_type else "commit")


class _CleanupAdminConnection:
    def __init__(
        self, *, fail_on: str | None = None, absent_triggers: frozenset[tuple[str, str]] = frozenset()
    ) -> None:
        self.events: list[str] = []
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self.fail_on = fail_on
        self.absent_triggers = absent_triggers

    def transaction(self) -> _CleanupTransaction:
        return _CleanupTransaction(self)

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> _CleanupCursor:
        self.executed.append((sql, params))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("synthetic cleanup failure")
        if sql == "SELECT to_regclass(%s)":
            assert params is not None
            return _CleanupCursor(row=(params[0],))
        if "FROM pg_catalog.pg_trigger" in sql:
            assert params is not None and len(params) == 2
            return _CleanupCursor(row=None if params in self.absent_triggers else (1,))
        if sql.startswith("SELECT "):
            return _CleanupCursor(rows=[])
        return _CleanupCursor()


def test_admin_postgres_test_cleanup_is_scoped_and_restores_immutable_trigger() -> None:
    admin = _CleanupAdminConnection()

    cleanup_postgres_test_tenants_as_admin(
        admin,
        tenant_ids=("payables_a_test", "payables_b_test"),
        plan=PAYABLES_TENANT_CLEANUP_PLAN,
    )

    assert admin.events == ["begin", "commit"]
    delete_calls = [(sql, params) for sql, params in admin.executed if sql.startswith("DELETE FROM")]
    assert delete_calls
    assert all(params == (["payables_a_test", "payables_b_test"],) for _, params in delete_calls)
    assert all("TRUNCATE" not in sql and "CASCADE" not in sql for sql, _ in admin.executed)
    disabled_at = next(
        index
        for index, (sql, _) in enumerate(admin.executed)
        if sql == "ALTER TABLE reconforge.domain_audit_events DISABLE TRIGGER domain_audit_events_immutable"
    )
    enabled_at = next(
        index
        for index, (sql, _) in enumerate(admin.executed)
        if sql == "ALTER TABLE reconforge.domain_audit_events ENABLE TRIGGER domain_audit_events_immutable"
    )
    first_delete_at = next(index for index, (sql, _) in enumerate(admin.executed) if sql.startswith("DELETE FROM"))
    constraints_checked_at = next(
        index for index, (sql, _) in enumerate(admin.executed) if sql == "SET CONSTRAINTS ALL IMMEDIATE"
    )
    assert disabled_at < first_delete_at < constraints_checked_at < enabled_at


def test_admin_postgres_test_cleanup_surfaces_delete_failures_and_rolls_back_trigger_state() -> None:
    admin = _CleanupAdminConnection(fail_on="DELETE FROM reconforge.domain_audit_events")

    with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
        cleanup_postgres_test_tenants_as_admin(
            admin,
            tenant_ids=("payables_a_test",),
            plan=PAYABLES_TENANT_CLEANUP_PLAN,
        )

    assert admin.events == ["begin", "rollback"]
    assert not any("ENABLE TRIGGER" in sql for sql, _ in admin.executed)


@pytest.mark.parametrize("namespace_installed", [False, True])
def test_admin_receivables_cleanup_only_toggles_installed_namespace_guards(namespace_installed: bool) -> None:
    namespace_guards = frozenset(
        {
            ("ar_idempotency_keys", "sales_receipt_name_immutable"),
            ("ar_idempotency_keys", "sales_receipt_name_key_closure"),
            ("ar_receipts", "sales_receipt_name_source_closure"),
        }
    )
    declared_namespace = frozenset(
        (trigger.table_name, trigger.trigger_name)
        for trigger in RECEIVABLES_TENANT_CLEANUP_PLAN.immutable_triggers
        if trigger.trigger_name.startswith("sales_receipt_name_")
    )
    assert declared_namespace == namespace_guards
    admin = _CleanupAdminConnection(absent_triggers=frozenset() if namespace_installed else namespace_guards)
    cleanup_postgres_test_tenants_as_admin(
        admin, tenant_ids=("receivables_owned_test",), plan=RECEIVABLES_TENANT_CLEANUP_PLAN
    )
    assert admin.events == ["begin", "commit"]
    calls = [statement for statement, _ in admin.executed]
    first_delete = next(index for index, statement in enumerate(calls) if statement.startswith("DELETE FROM"))
    constraints_checked = calls.index("SET CONSTRAINTS ALL IMMEDIATE")
    for table, trigger in namespace_guards:
        disabled = f"ALTER TABLE reconforge.{table} DISABLE TRIGGER {trigger}"
        enabled = f"ALTER TABLE reconforge.{table} ENABLE TRIGGER {trigger}"
        if namespace_installed:
            assert calls.index(disabled) < first_delete < constraints_checked < calls.index(enabled)
        else:
            assert disabled not in calls and enabled not in calls
    assert all(
        params == (["receivables_owned_test"],)
        for statement, params in admin.executed
        if statement.startswith("DELETE FROM")
    )
    assert not any("TRIGGER USER" in statement or "TRIGGER ALL" in statement for statement in calls)


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
    assert pool.snapshot == PostgresConnectionPoolSnapshot(max_size=1, total=0, idle=0, leased=0, closed=True)


def test_postgres_connection_pool_snapshot_and_repeated_multithreaded_lifecycle_are_bounded() -> None:
    connections: list[_FakeConnection] = []

    class _Factory:
        def connect(self) -> _FakeConnection:
            connection = _FakeConnection()
            connections.append(connection)
            return connection

    pool = PostgresConnectionPool(_Factory(), max_size=4, acquire_timeout_seconds=2.0)

    def lease_once(_: int) -> None:
        connection = pool.connect()
        connection.close()

    with ThreadPoolExecutor(max_workers=16, thread_name_prefix="pool-lifecycle") as workers:
        list(workers.map(lease_once, range(128)))

    snapshot = pool.snapshot
    assert snapshot.max_size == 4
    assert 0 <= snapshot.total <= 4
    assert snapshot.idle == snapshot.total
    assert snapshot.leased == 0
    assert len(connections) <= 4
    pool.close()
    assert pool.snapshot == PostgresConnectionPoolSnapshot(max_size=4, total=0, idle=0, leased=0, closed=True)
    with pytest.raises(PostgresConnectionPoolClosedError):
        pool.connect()


def test_pooled_connection_factory_reuses_connections_and_preserves_factory_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[_FakeConnection] = []

    def fake_connect(_dsn: str, **_kwargs: object) -> _FakeConnection:
        connection = _FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(
        "reconforge.infrastructure.postgres._load_psycopg",
        lambda: SimpleNamespace(connect=fake_connect),
    )

    factory = PostgresPooledConnectionFactory(
        PostgresSettings(dsn="postgresql://db/reconforge"),
        max_size=1,
        acquire_timeout_seconds=0.1,
    )
    assert isinstance(factory, PostgresConnectionFactory)
    first = factory.connect()
    first.close()
    second = factory.connect()
    second.close()

    assert len(connections) == 1
    factory.close()
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
    pytest.importorskip("psycopg")

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_settings = PostgresSettings(dsn=dsn, require_tls=False)
    admin_settings = PostgresSettings(dsn=admin_dsn, require_tls=False)
    factory = PostgresConnectionFactory(app_settings)
    admin_factory = PostgresConnectionFactory(admin_settings)
    admin = admin_factory.connect()
    app = factory.connect()
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    tenant_a = "test_rls_a_" + uuid4().hex[:8]
    tenant_b = "test_rls_b_" + uuid4().hex[:8]
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

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            connection.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tenant_a, "A"))
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            connection.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tenant_b, "B"))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            rows = connection.execute("SELECT id FROM reconforge.tenants ORDER BY id").fetchall()
            assert [row[0] for row in rows] == [tenant_a]
    finally:
        try:
            cleanup_postgres_test_tenants_as_admin(
                admin,
                tenant_ids=(tenant_a, tenant_b),
                plan=RLS_TENANT_CLEANUP_PLAN,
            )
        finally:
            app.close()
            admin.close()
