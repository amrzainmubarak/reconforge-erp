from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.close import CloseManagementRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_close_application import (
    POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL,
    PostgresCloseManagementRepository,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0030_postgres_close_application.py"
    spec = importlib.util.spec_from_file_location("migration_0030", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_close_application_schema_is_additive_exact_and_forced_rls() -> None:
    for table in (
        "close_application_periods", "close_application_tasks", "close_application_dependencies"
    ):
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
        assert f"'{table}'" in POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
    assert "readiness_score NUMERIC(5,2)" in POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS reconforge.close_periods" not in POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL


def test_close_application_schema_guards_lifecycle_tasks_dag_and_lock_evidence() -> None:
    schema = POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
    assert "invalid close period status transition" in schema
    assert "locking a close period requires complete tasks and actor evidence" in schema
    assert "reopening a close period requires actor reason and timestamp" in schema
    assert "tasks in a locked close period are immutable" in schema
    assert "blocked close tasks require an exclusive blocker reason" in schema
    assert "close task dependency would create a cycle" in schema


def test_close_application_migration_is_linear_child_first_and_preserves_legacy_tables() -> None:
    migration = _migration()
    assert migration.revision == "0030_postgres_close_app"
    assert migration.down_revision == "0029_postgres_approvals"
    source = (ROOT / "alembic/versions/0030_postgres_close_application.py").read_text(encoding="utf-8")
    assert source.index("close_application_dependencies CASCADE") < source.index(
        "close_application_periods CASCADE"
    )
    assert "reconforge.close_periods" not in source


def test_close_application_adapter_matches_all_eleven_application_signatures() -> None:
    methods = [
        name for name, value in vars(CloseManagementRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(methods) == 11
    for name in methods:
        assert inspect.signature(getattr(PostgresCloseManagementRepository, name)) == inspect.signature(
            getattr(CloseManagementRepositoryProtocol, name)
        )


def test_close_application_adapter_uses_serialization_exact_readiness_and_transactional_evidence() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_close_application.py").read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in source
    assert "FOR UPDATE" in source
    assert "readiness_percentage" in source
    assert "COMPLETE_READINESS" in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source
    assert "LIMIT 10000" in source
    assert "requests." not in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_close_dag_readiness_lock_reopen_and_rls() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a, tenant_b = "closeapp_a_" + uuid4().hex[:8], "closeapp_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'finance')",
                    (tenant, f"workspace-{tenant}"),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            close = PostgresCloseManagementRepository(connection, tenant_a)
            period = close.period_init(
                period_name="2026-07", start_date="2026-07-01", end_date="2026-07-31",
                workspace="finance", actor_label="controller", with_default_tasks=False,
            )
            with pytest.raises(PlatformError, match="overlap"):
                close.period_init(
                    period_name="overlap", start_date="2026-07-15", end_date="2026-08-15",
                    workspace="finance", actor_label="controller", with_default_tasks=False,
                )
            tasks = [
                close.task_add(period_id=str(period["id"]), task_code=code, name=code, actor_label="controller")
                for code in ("A", "B", "C")
            ]
            close.task_dependency(
                task_id=str(tasks[0]["id"]), depends_on_task_id=str(tasks[1]["id"]), actor_label="controller"
            )
            close.task_dependency(
                task_id=str(tasks[1]["id"]), depends_on_task_id=str(tasks[2]["id"]), actor_label="controller"
            )
            with pytest.raises(PlatformError, match="cycle"):
                close.task_dependency(
                    task_id=str(tasks[2]["id"]), depends_on_task_id=str(tasks[0]["id"]),
                    actor_label="controller",
                )
            with pytest.raises(PlatformError, match="dependencies are incomplete"):
                close.task_status(task_id=str(tasks[0]["id"]), status="Complete", actor_label="controller")
            for task in reversed(tasks):
                close.task_status(task_id=str(task["id"]), status="Complete", actor_label="controller")
            readiness = close.readiness(period_id=str(period["id"]), actor_label="controller")
            assert (readiness.total_tasks, readiness.complete_tasks, readiness.readiness_score) == (3, 3, 100)
            locked = close.lock_period(str(period["id"]), actor_label="controller")
            assert locked["status"] == "Locked"
            with pytest.raises(PlatformError, match="locked close period"):
                close.task_status(task_id=str(tasks[0]["id"]), status="In Progress", actor_label="controller")
            reopened = close.reopen_period(
                str(period["id"]), reason="Late evidence received", actor_label="controller"
            )
            assert (reopened["status"], reopened["reopen_reason"]) == ("Reopened", "Late evidence received")
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0]
            outbox_count = connection.execute(
                "SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0]
            assert audit_count == outbox_count == 12
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            close_b = PostgresCloseManagementRepository(connection, tenant_b)
            assert close_b.list_periods() == []
            assert close_b.list_tasks() == []
            with pytest.raises(PlatformError, match="not found"):
                close_b.get_period(str(period["id"]))
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
