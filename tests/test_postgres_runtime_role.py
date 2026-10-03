"""Runtime credentials must preserve PostgreSQL's RLS boundary on each lease."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.infrastructure.postgres import (
    _RUNTIME_ROLE_SAFETY_SQL,
    PostgresConnectionFactory,
    PostgresConnectionPool,
    PostgresRuntimeConnectionFactory,
    PostgresRuntimePooledConnectionFactory,
    PostgresRuntimeRoleError,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.workers.outbox import OutboxWorkerSettings
from reconforge.workers.postgres_outbox import PostgresOutboxWorker
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
)
from reconforge.workers.postgres_scheduler import (
    PostgresSchedulerWorker,
    PostgresSchedulerWorkerSettings,
)
from tests.test_alembic_postgres import (
    isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn,
)

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


class _CatalogConnection:
    def __init__(self, row: Any = (True,), *, failure: bool = False) -> None:
        self.row = row
        self.failure = failure
        self.closed = False
        self.checks = 0
        self.rollbacks = 0

    def execute(self, query: str) -> Any:
        assert query == _RUNTIME_ROLE_SAFETY_SQL
        self.checks += 1
        if self.failure:
            raise RuntimeError("postgresql://private:do-not-expose@internal/db")
        return SimpleNamespace(fetchone=lambda: self.row)

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("row", [None, (False,), (None,), (1,), ()])
def test_runtime_factory_rejects_unsafe_or_incomplete_catalog_result(row: Any) -> None:
    connection = _CatalogConnection(row)
    factory = PostgresRuntimeConnectionFactory(SimpleNamespace(connect=lambda: connection))
    with pytest.raises(PostgresRuntimeRoleError, match="runtime role safety check failed"):
        factory.connect()
    assert connection.closed
    assert connection.checks == 1


def test_runtime_pool_discards_query_failure_and_does_not_leak_connection_details() -> None:
    connection = _CatalogConnection(failure=True)
    pool = PostgresConnectionPool(SimpleNamespace(connect=lambda: connection), max_size=1)
    factory = PostgresRuntimeConnectionFactory(pool)
    with pytest.raises(PostgresRuntimeRoleError) as error:
        factory.connect()
    assert "private" not in str(error.value)
    assert "internal" not in str(error.value)
    assert error.value.__suppress_context__
    assert connection.closed
    assert pool.snapshot.total == pool.snapshot.idle == pool.snapshot.leased == 0
    pool.close()


def test_runtime_connection_acquisition_failure_does_not_expose_driver_message() -> None:
    def broken_connect() -> Any:
        raise RuntimeError("postgresql://private:do-not-expose@internal/db")

    factory = PostgresRuntimeConnectionFactory(SimpleNamespace(connect=broken_connect))
    with pytest.raises(PostgresRuntimeRoleError, match="runtime connection unavailable") as error:
        factory.connect()
    assert "private" not in str(error.value)
    assert "internal" not in str(error.value)
    assert error.value.__suppress_context__


def test_runtime_guard_rechecks_reused_pool_leases_and_does_not_duplicate_nested_checks() -> None:
    connection = _CatalogConnection()
    pool = PostgresConnectionPool(SimpleNamespace(connect=lambda: connection), max_size=1)
    factory = PostgresRuntimeConnectionFactory(PostgresRuntimeConnectionFactory(pool))
    factory.connect().close()
    assert connection.checks == 1
    connection.row = (False,)
    with pytest.raises(PostgresRuntimeRoleError):
        factory.connect()
    assert connection.checks == 2
    assert connection.closed
    assert pool.snapshot.total == 0
    factory.close()


def _worker(kind: str, raw_factory: Any, callback_calls: list[Any]) -> Any:
    if kind == "outbox":
        return PostgresOutboxWorker(
            raw_factory,
            tenant_supplier=lambda: ["tenant_a"],
            publisher=callback_calls.append,
            settings=OutboxWorkerSettings(worker_id="worker", allow_unbound_hosted_policy=True),
        )
    if kind == "scheduler":
        return PostgresSchedulerWorker(
            raw_factory,
            tenant_supplier=lambda: ["tenant_a"],
            settings=PostgresSchedulerWorkerSettings(worker_id="worker", allow_unbound_hosted_policy=True),
        )
    return PostgresReconciliationWorker(
        raw_factory,
        tenant_supplier=lambda: ["tenant_a"],
        matcher=callback_calls.append,
        settings=PostgresReconciliationWorkerSettings(worker_id="worker", allow_unbound_hosted_policy=True),
    )


@pytest.mark.parametrize("kind", ["outbox", "scheduler", "reconciliation"])
def test_worker_checks_role_before_any_application_query_or_callback(kind: str) -> None:
    connection = _CatalogConnection((False,))
    callback_calls: list[Any] = []
    worker = _worker(kind, SimpleNamespace(connect=lambda: connection), callback_calls)
    with pytest.raises((PostgresRuntimeRoleError, RuntimeError)):
        worker.process_once()
    assert connection.checks == 1
    assert connection.closed
    assert callback_calls == []


@pytest.fixture
def role_database(isolated_postgres_migration_dsn: str) -> Iterator[Any]:
    psycopg = pytest.importorskip("psycopg")
    names = {label: "rf_runtime_" + label + "_" + uuid4().hex[:16] for label in ("login", "hop", "owner", "unsafe")}
    admin = psycopg.connect(isolated_postgres_migration_dsn, autocommit=True)
    created: list[str] = []

    def sql(statement: str, *identifiers: str) -> Any:
        return admin.execute(psycopg.sql.SQL(statement).format(*(psycopg.sql.Identifier(item) for item in identifiers)))

    try:
        for label, name in names.items():
            sql("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB", name)
            created.append(name)
            if label == "login":
                sql("ALTER ROLE {} LOGIN NOINHERIT PASSWORD 'synthetic_runtime_only'", name)
        admin.execute("CREATE SCHEMA reconforge")
        admin.execute("CREATE TABLE reconforge.runtime_probe (tenant_id text NOT NULL)")
        admin.execute("ALTER TABLE reconforge.runtime_probe ENABLE ROW LEVEL SECURITY")
        admin.execute("ALTER TABLE reconforge.runtime_probe FORCE ROW LEVEL SECURITY")
        admin.execute(
            "CREATE POLICY tenant_scope ON reconforge.runtime_probe "
            "USING (tenant_id = current_setting('app.tenant_id', true))"
        )
        admin.execute("INSERT INTO reconforge.runtime_probe VALUES ('tenant_a'), ('tenant_b')")
        sql("GRANT USAGE ON SCHEMA reconforge TO {}", names["login"])
        sql("GRANT SELECT ON reconforge.runtime_probe TO {}", names["login"])
        parameters = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)
        parameters.update(user=names["login"], password="synthetic_runtime_only")
        settings = PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**parameters), require_tls=False)
        yield SimpleNamespace(admin=admin, sql=sql, names=names, settings=settings)
    finally:
        for name in reversed(created):
            sql("REASSIGN OWNED BY {} TO CURRENT_USER", name)
            sql("DROP OWNED BY {}", name)
            sql("DROP ROLE {}", name)
        admin.close()


def _assert_rejected(database: Any) -> None:
    factory = PostgresRuntimePooledConnectionFactory(database.settings, max_size=1)
    try:
        with pytest.raises(PostgresRuntimeRoleError, match="runtime role safety check failed"):
            factory.connect()
        assert factory.pool_snapshot.total == 0
    finally:
        factory.close()


def _grant_runtime_capability(database: Any, capability: str, recipient: str) -> None:
    if capability in {"TRUNCATE", "TRIGGER", "REFERENCES"}:
        database.sql(f"GRANT {capability} ON reconforge.runtime_probe TO {{}}", recipient)
    elif capability == "schema_create":
        database.sql("GRANT CREATE ON SCHEMA reconforge TO {}", recipient)
    elif capability == "database_create":
        name = database.admin.execute("SELECT current_database()").fetchone()[0]
        database.sql("GRANT CREATE ON DATABASE {} TO {}", name, recipient)
    else:
        database.admin.execute(
            "CREATE FUNCTION reconforge.runtime_definer() RETURNS bigint "
            "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog "
            "AS 'SELECT count(*) FROM reconforge.runtime_probe'"
        )
        database.admin.execute("REVOKE EXECUTE ON FUNCTION reconforge.runtime_definer() FROM PUBLIC")
        database.sql("GRANT EXECUTE ON FUNCTION reconforge.runtime_definer() TO {}", recipient)


@pytest.mark.parametrize("capability", [
    "TRUNCATE", "TRIGGER", "REFERENCES", "schema_create", "database_create", "definer_execute",
])
@pytest.mark.parametrize("route", ["direct", "inherited", "set_then_inherited", "admin_then_inherited"])
def test_live_runtime_rejects_bypass_capability_grants(role_database: Any, capability: str, route: str) -> None:
    database = role_database
    login, hop, unsafe = (database.names[key] for key in ("login", "hop", "unsafe"))
    recipient = login if route == "direct" else unsafe
    _grant_runtime_capability(database, capability, recipient)
    if route == "inherited":
        database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", unsafe, login)
    elif route != "direct":
        database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", unsafe, hop)
        if route == "set_then_inherited":
            database.sql("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE", hop, login)
        else:
            database.sql("GRANT {} TO {} WITH ADMIN TRUE, INHERIT FALSE, SET FALSE", hop, login)
    _assert_rejected(database)


def test_live_truncate_bypasses_rls_even_with_transaction_tenant_scope(role_database: Any) -> None:
    database = role_database
    _grant_runtime_capability(database, "TRUNCATE", database.names["login"])
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database.settings.dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', 'tenant_a', true)")
        assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 1
        connection.execute("TRUNCATE reconforge.runtime_probe")
        connection.execute("SELECT set_config('app.tenant_id', 'tenant_b', true)")
        assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 0
        connection.rollback()
    assert database.admin.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 2
    _assert_rejected(database)


def test_live_public_definer_execute_reads_other_tenant_despite_rls(role_database: Any) -> None:
    database = role_database
    _grant_runtime_capability(database, "definer_execute", database.names["unsafe"])
    database.admin.execute("GRANT EXECUTE ON FUNCTION reconforge.runtime_definer() TO PUBLIC")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database.settings.dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', 'tenant_a', true)")
        assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 1
        assert connection.execute("SELECT reconforge.runtime_definer()").fetchone()[0] == 2
    _assert_rejected(database)


@pytest.mark.parametrize("capability", [
    "TRUNCATE", "TRIGGER", "REFERENCES", "schema_create", "database_create", "definer_execute",
])
def test_live_unreachable_capability_role_does_not_reject_safe_login(role_database: Any, capability: str) -> None:
    database = role_database
    _grant_runtime_capability(database, capability, database.names["unsafe"])
    database.sql(
        "GRANT {} TO {} WITH ADMIN FALSE, INHERIT FALSE, SET FALSE",
        database.names["unsafe"], database.names["login"],
    )
    factory = PostgresRuntimePooledConnectionFactory(database.settings, max_size=1)
    try:
        connection = factory.connect()
        assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 0
        connection.close()
    finally:
        factory.close()


def test_live_public_schema_create_is_not_a_safe_runtime_default(role_database: Any) -> None:
    role_database.admin.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
    _assert_rejected(role_database)


def test_live_public_definer_procedure_is_rejected(role_database: Any) -> None:
    role_database.admin.execute(
        "CREATE PROCEDURE reconforge.runtime_definer_procedure() LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = pg_catalog AS 'BEGIN NULL; END'"
    )
    _assert_rejected(role_database)


def test_live_installed_definer_trigger_does_not_require_runtime_ddl_or_direct_execution(role_database: Any) -> None:
    database = role_database
    database.admin.execute(
        "CREATE FUNCTION reconforge.runtime_trigger() RETURNS trigger LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = pg_catalog AS 'BEGIN RETURN NEW; END'"
    )
    database.admin.execute(
        "CREATE TRIGGER runtime_guard BEFORE INSERT ON reconforge.runtime_probe "
        "FOR EACH ROW EXECUTE FUNCTION reconforge.runtime_trigger()"
    )
    database.sql("GRANT INSERT ON reconforge.runtime_probe TO {}", database.names["login"])
    factory = PostgresRuntimePooledConnectionFactory(database.settings, max_size=1)
    try:
        boundary = PostgresTenantBoundary(factory)
        with boundary.transaction("tenant_a") as connection:
            connection.execute("INSERT INTO reconforge.runtime_probe VALUES ('tenant_a')")
            assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 2
        with boundary.transaction("tenant_b") as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 1
    finally:
        factory.close()


def test_live_pool_discards_new_truncate_grant_and_recovers_after_revoke(role_database: Any) -> None:
    database = role_database
    factory = PostgresRuntimePooledConnectionFactory(database.settings, max_size=1)
    try:
        connection = factory.connect()
        pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        connection.close()
        _grant_runtime_capability(database, "TRUNCATE", database.names["login"])
        with pytest.raises(PostgresRuntimeRoleError):
            factory.connect()
        assert factory.pool_snapshot.total == 0
        database.sql("REVOKE TRUNCATE ON reconforge.runtime_probe FROM {}", database.names["login"])
        connection = factory.connect()
        assert connection.execute("SELECT pg_backend_pid()").fetchone()[0] != pid
        connection.close()
    finally:
        factory.close()


@pytest.mark.parametrize("attribute", ["SUPERUSER", "BYPASSRLS", "CREATEROLE", "CREATEDB", "REPLICATION"])
def test_live_runtime_rejects_privileged_login_role(role_database: Any, attribute: str) -> None:
    role_database.sql(f"ALTER ROLE {{}} {attribute}", role_database.names["login"])
    _assert_rejected(role_database)


@pytest.mark.parametrize("kind", ["table", "schema", "database", "routine"])
def test_live_runtime_rejects_owner_even_when_table_forces_rls(role_database: Any, kind: str) -> None:
    database = role_database
    owner = database.names["login"]
    if kind == "table":
        database.sql("ALTER TABLE reconforge.runtime_probe OWNER TO {}", owner)
    elif kind == "schema":
        database.sql("ALTER SCHEMA reconforge OWNER TO {}", owner)
    elif kind == "routine":
        database.admin.execute("CREATE FUNCTION reconforge.runtime_probe_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'")
        database.sql("ALTER FUNCTION reconforge.runtime_probe_fn() OWNER TO {}", owner)
    else:
        name = database.admin.execute("SELECT current_database()").fetchone()[0]
        database.sql("ALTER DATABASE {} OWNER TO {}", name, owner)
    _assert_rejected(database)


def test_live_set_role_chain_is_distinct_from_inheriting_special_role_flags(role_database: Any) -> None:
    database = role_database
    login, hop, unsafe = (database.names[key] for key in ("login", "hop", "unsafe"))
    database.sql("ALTER ROLE {} BYPASSRLS", unsafe)
    database.sql("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE", hop, login)
    database.sql("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE", unsafe, hop)
    _assert_rejected(database)
    database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", unsafe, hop)
    factory = PostgresRuntimePooledConnectionFactory(database.settings)
    try:
        connection = factory.connect()
        assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 0
        connection.close()
    finally:
        factory.close()


def test_live_set_role_can_inherit_ownership_through_a_non_settable_second_role(role_database: Any) -> None:
    database = role_database
    login, hop, owner = (database.names[key] for key in ("login", "hop", "owner"))
    database.sql("ALTER TABLE reconforge.runtime_probe OWNER TO {}", owner)
    database.sql("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE", hop, login)
    database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", owner, hop)
    _assert_rejected(database)


def test_live_admin_option_cannot_hide_a_bypass_role_behind_set_false(role_database: Any) -> None:
    database = role_database
    database.sql("ALTER ROLE {} BYPASSRLS", database.names["unsafe"])
    database.sql(
        "GRANT {} TO {} WITH ADMIN TRUE, INHERIT FALSE, SET FALSE",
        database.names["unsafe"], database.names["login"],
    )
    _assert_rejected(database)
    # Prove why ADMIN without SET is unsafe rather than assuming flag equivalence.
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database.settings.dsn, autocommit=True) as connection:
        assert connection.execute(
            "SELECT pg_has_role(session_user, %s, 'SET')", (database.names["unsafe"],)
        ).fetchone()[0] is False
        connection.execute(psycopg.sql.SQL("GRANT {} TO {} WITH SET TRUE").format(
            psycopg.sql.Identifier(database.names["unsafe"]), psycopg.sql.Identifier(database.names["login"]),
        ))
        assert connection.execute(
            "SELECT pg_has_role(session_user, %s, 'SET')", (database.names["unsafe"],)
        ).fetchone()[0] is True


@pytest.mark.parametrize("role", ["pg_read_server_files", "pg_write_server_files", "pg_execute_server_program"])
def test_live_runtime_rejects_inherited_server_file_or_program_privileges(role_database: Any, role: str) -> None:
    database = role_database
    database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", role, database.names["login"])
    _assert_rejected(database)


def test_live_admin_then_set_chain_cannot_hide_inherited_ownership(role_database: Any) -> None:
    database = role_database
    login, hop, owner, unsafe = (database.names[key] for key in ("login", "hop", "owner", "unsafe"))
    database.sql("ALTER TABLE reconforge.runtime_probe OWNER TO {}", owner)
    database.sql("GRANT {} TO {} WITH ADMIN TRUE, INHERIT FALSE, SET FALSE", hop, login)
    database.sql("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE", unsafe, hop)
    database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", owner, unsafe)
    _assert_rejected(database)


def test_live_inherited_admin_option_can_enable_set_role_and_must_be_rejected(role_database: Any) -> None:
    database = role_database
    login, hop, unsafe = (database.names[key] for key in ("login", "hop", "unsafe"))
    database.sql("ALTER ROLE {} BYPASSRLS", unsafe)
    database.sql("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE", hop, login)
    database.sql("GRANT {} TO {} WITH ADMIN TRUE, INHERIT FALSE, SET FALSE", unsafe, hop)
    _assert_rejected(database)
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database.settings.dsn, autocommit=True) as connection:
        assert connection.execute("SELECT pg_has_role(session_user, %s, 'SET')", (unsafe,)).fetchone()[0] is False
        connection.execute(psycopg.sql.SQL("GRANT {} TO {} WITH SET TRUE").format(
            psycopg.sql.Identifier(unsafe), psycopg.sql.Identifier(login),
        ))
        assert connection.execute("SELECT pg_has_role(session_user, %s, 'SET')", (unsafe,)).fetchone()[0] is True


def test_live_pool_rechecks_privilege_drift_and_recovers_with_a_new_physical_connection(role_database: Any) -> None:
    database = role_database
    factory = PostgresRuntimePooledConnectionFactory(database.settings, max_size=1)
    try:
        first = factory.connect()
        pid = first.execute("SELECT pg_backend_pid()").fetchone()[0]
        first.close()
        reused = factory.connect()
        assert reused.execute("SELECT pg_backend_pid()").fetchone()[0] == pid
        reused.close()
        database.sql("ALTER ROLE {} BYPASSRLS", database.names["login"])
        with pytest.raises(PostgresRuntimeRoleError):
            factory.connect()
        assert factory.pool_snapshot.total == 0
        database.sql("ALTER ROLE {} NOBYPASSRLS", database.names["login"])
        restored = factory.connect()
        assert restored.execute("SELECT pg_backend_pid()").fetchone()[0] != pid
        restored.close()
    finally:
        factory.close()


@pytest.mark.parametrize("change", ["role", "row_security", "tenant_scope"])
def test_live_pool_rejects_persisted_session_changes(role_database: Any, change: str) -> None:
    database = role_database
    database.sql("GRANT {} TO {}", database.names["hop"], database.names["login"])
    factory = PostgresRuntimePooledConnectionFactory(database.settings, max_size=1)
    try:
        connection = factory.connect()
        with connection.transaction():
            if change == "role":
                psycopg = pytest.importorskip("psycopg")
                connection.execute(psycopg.sql.SQL("SET ROLE {}").format(psycopg.sql.Identifier(database.names["hop"])))
            elif change == "row_security":
                connection.execute("SET row_security = off")
            else:
                connection.execute("SELECT set_config('app.tenant_id', 'tenant_a', false)")
        connection.close()
        with pytest.raises(PostgresRuntimeRoleError):
            factory.connect()
        assert factory.pool_snapshot.total == 0
    finally:
        factory.close()


def test_live_runtime_pool_accepts_transaction_local_scope_without_retaining_a_previous_tenant(role_database: Any) -> None:
    factory = PostgresRuntimePooledConnectionFactory(role_database.settings, max_size=1)
    try:
        boundary = PostgresTenantBoundary(factory)
        for tenant in ("tenant_a", "tenant_b", "tenant_a"):
            with boundary.transaction(tenant) as connection:
                assert tuple(connection.execute("SELECT tenant_id FROM reconforge.runtime_probe").fetchone()) == (tenant,)
        connection = factory.connect()
        assert connection.execute("SELECT count(*) FROM reconforge.runtime_probe").fetchone()[0] == 0
        connection.close()
        assert factory.pool_snapshot.total == factory.pool_snapshot.idle == 1
    finally:
        factory.close()


def test_live_admin_factory_remains_usable_but_api_health_rejects_unsafe_role(
    isolated_postgres_migration_dsn: str, tmp_path: Path,
) -> None:
    settings = PostgresSettings(dsn=isolated_postgres_migration_dsn, require_tls=False)
    connection = PostgresConnectionFactory(settings).connect()
    assert connection.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]
    connection.close()
    api = create_api_app(
        tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants",
        postgres_dsn=isolated_postgres_migration_dsn, postgres_require_tls=False,
    )
    assert isinstance(api.state.postgres_identity_factory, PostgresRuntimePooledConnectionFactory)
    with TestClient(api) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["database"]["reachable"] is False
        assert "synthetic_audit_only" not in response.text
        assert "runtime role safety" not in response.text
        assert api.state.postgres_identity_factory.pool_snapshot.total == 0


@pytest.mark.parametrize("kind", ["outbox", "scheduler", "reconciliation"])
def test_live_worker_rejects_admin_factory_before_any_business_query(
    isolated_postgres_migration_dsn: str, kind: str,
) -> None:
    callback_calls: list[Any] = []
    factory = PostgresConnectionFactory(PostgresSettings(dsn=isolated_postgres_migration_dsn, require_tls=False))
    worker = _worker(kind, factory, callback_calls)
    with pytest.raises((PostgresRuntimeRoleError, RuntimeError)) as error:
        worker.process_once()
    assert callback_calls == []
    # No business tables exist in this database, so reaching a repository would
    # instead report UndefinedTable. Follow the safe wrapper's explicit cause.
    cause = error.value.__cause__ or error.value
    assert isinstance(cause, PostgresRuntimeRoleError)
