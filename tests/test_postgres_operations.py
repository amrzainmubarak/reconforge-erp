from __future__ import annotations

import ast
import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.operations import MigrationStatus, OperationsApplicationService
from reconforge.application.workspace_periods import WorkspacePeriodApplicationService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import (
    PostgresDomainUnitOfWork,
    install_postgres_domain_schema,
)
from reconforge.infrastructure.postgres_operations import (
    POSTGRES_MIGRATION_REVISIONS,
    POSTGRES_OPERATIONS_SCHEMA_SQL,
    PostgresOperationsRepository,
    install_postgres_operations_schema,
)
from reconforge.infrastructure.sqlite_operations import SQLiteOperationsRepository, sqlite_migration_status

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_operations_schema_and_revision_registry_are_explicit() -> None:
    assert POSTGRES_OPERATIONS_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 2
    assert "FOREIGN KEY (tenant_id, workspace_id)" in POSTGRES_OPERATIONS_SCHEMA_SQL
    assert POSTGRES_MIGRATION_REVISIONS[-1] == "0054_pg_consol_ownership"
    assert len(POSTGRES_MIGRATION_REVISIONS) == 54


def test_postgres_operations_revision_registry_matches_the_linear_alembic_chain() -> None:
    discovered: list[str] = []
    previous: str | None = None
    for path in sorted((ROOT / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assignments = {
            target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}
        }
        assert assignments["down_revision"] == previous, f"{path.name} breaks the linear migration chain"
        previous = str(assignments["revision"])
        discovered.append(previous)
    assert tuple(discovered) == POSTGRES_MIGRATION_REVISIONS


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_operations_are_tenant_scoped_and_not_reported_local_only(
    tmp_path: Path,
) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "operations_live_a_" + uuid4().hex[:8]
    tenant_b = "operations_live_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            install_postgres_operations_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.domain_workspaces, "
                f"reconforge.domain_periods, reconforge.domain_audit_ledger_state, "
                f"reconforge.domain_audit_events, reconforge.ops_job_history, "
                f"reconforge.ops_error_records TO {app_user}"
            )
            for tenant in (tenant_a, tenant_b):
                admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant, tenant))
        setup = WorkspacePeriodApplicationService(
            lambda: PostgresDomainUnitOfWork(factory, tenant_a)
        ).create(
            workspace_name="Operations", period_name="2026-Q3",
            start_date="2026-07-01", end_date="2026-09-30", actor_label="controller",
        )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            connection.execute(
                """
                INSERT INTO reconforge.ops_job_history
                    (tenant_id,id,workspace_id,job_type,status,summary,started_at,completed_at)
                VALUES (%s,'JOB-1',%s,'import','completed','safe','2026-01-01T00:00:00Z',NULL)
                """,
                (tenant_a, setup.workspace.id),
            )
            connection.execute(
                """
                INSERT INTO reconforge.ops_error_records
                    (tenant_id,id,workspace_id,source,error_code,message,created_at)
                VALUES (%s,'ERR-1',%s,'worker','SAFE-1','redacted','2026-01-01T00:00:00Z')
                """,
                (tenant_a, setup.workspace.id),
            )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresOperationsRepository(connection, tenant_a)
            service = OperationsApplicationService(
                repository,
                lambda locator: MigrationStatus("0014_postgres_operations", "0014_postgres_operations", ()),
            )
            postgres_jobs = service.jobs()
            postgres_errors = service.errors()
            assert postgres_jobs == [{
                "id": "JOB-1", "workspace_id": setup.workspace.id, "job_type": "import",
                "status": "completed", "summary": "safe", "started_at": "2026-01-01T00:00:00Z",
                "completed_at": None,
            }]
            assert postgres_errors == [{
                "id": "ERR-1", "workspace_id": setup.workspace.id, "source": "worker",
                "error_code": "SAFE-1", "message": "redacted", "created_at": "2026-01-01T00:00:00Z",
            }]
            health = service.health("postgres-primary")
            assert health["database_reachable"] is True
            assert health["audit_chain_ok"] is True
            assert health["job_records"] == health["error_records"] == 1
            assert health["local_only"] is False
        sqlite_path = tmp_path / "operations-parity.db"
        run_migrations(sqlite_path)
        sqlite_connection = connect(sqlite_path, require_exists=True)
        try:
            sqlite_connection.execute(
                "INSERT INTO workspaces (id,name,local_first_note,created_at) VALUES (?,?,?,?)",
                (setup.workspace.id, "Operations", "", "2026-01-01T00:00:00Z"),
            )
            sqlite_connection.execute(
                "INSERT INTO ops_job_history "
                "(id,workspace_id,job_type,status,summary,started_at,completed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("JOB-1", setup.workspace.id, "import", "completed", "safe",
                 "2026-01-01T00:00:00Z", None),
            )
            sqlite_connection.execute(
                "INSERT INTO ops_error_records "
                "(id,workspace_id,source,error_code,message,created_at) VALUES (?,?,?,?,?,?)",
                ("ERR-1", setup.workspace.id, "worker", "SAFE-1", "redacted",
                 "2026-01-01T00:00:00Z"),
            )
            sqlite_connection.commit()
            sqlite_service = OperationsApplicationService(
                SQLiteOperationsRepository(sqlite_connection), sqlite_migration_status
            )
            assert sqlite_service.jobs() == postgres_jobs
            assert sqlite_service.errors() == postgres_errors
            assert sqlite_service.health(str(sqlite_path))["local_only"] is True
        finally:
            sqlite_connection.close()
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            isolated = PostgresOperationsRepository(connection, tenant_b)
            assert isolated.record_counts() == (0, 0)
            assert isolated.list_jobs() == [] and isolated.list_errors() == []
            assert isolated.audit_chain_ok() is True
    finally:
        admin.close()
