from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.workspace_periods import WorkspacePeriodApplicationService
from reconforge.audit.events import AuditLedgerError
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import (
    POSTGRES_DOMAIN_SCHEMA_SQL,
    PostgresDomainUnitOfWork,
    install_postgres_domain_schema,
)
from reconforge.infrastructure.sqlite_domain import SQLiteDomainUnitOfWork


def test_postgres_domain_schema_forces_rls_and_append_only_audit() -> None:
    assert POSTGRES_DOMAIN_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 4
    assert "UNIQUE (tenant_id, sequence)" in POSTGRES_DOMAIN_SCHEMA_SQL
    assert "Domain audit events are append-only" in POSTGRES_DOMAIN_SCHEMA_SQL
    assert "FOREIGN KEY (tenant_id, workspace_id)" in POSTGRES_DOMAIN_SCHEMA_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_workspace_period_uow_is_atomic_tenant_scoped_and_verifiable(
    tmp_path: Path,
) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "domain_live_a_" + uuid4().hex[:8]
    tenant_b = "domain_live_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.domain_workspaces, "
                f"reconforge.domain_periods, reconforge.domain_audit_ledger_state, "
                f"reconforge.domain_audit_events TO {app_user}"
            )
            for tenant in (tenant_a, tenant_b):
                admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant, tenant))

        service = WorkspacePeriodApplicationService(
            lambda: PostgresDomainUnitOfWork(factory, tenant_a)
        )
        result = service.create(
            workspace_name=" Cairo controls ", period_name=" 2026-Q3 ",
            start_date="2026-07-01", end_date="2026-09-30", actor_label=" controller ",
        )
        assert result.workspace.name == "Cairo controls"
        assert result.period.workspace_id == result.workspace.id
        assert [event.action for event in result.audit_events] == ["workspace.created", "period.created"]
        assert result.audit_events[1].previous_hash == result.audit_events[0].event_hash

        sqlite_path = tmp_path / "workspace-period-parity.db"
        run_migrations(sqlite_path)
        sqlite_connection = connect(sqlite_path, require_exists=True)
        try:
            sqlite_result = WorkspacePeriodApplicationService(
                lambda: SQLiteDomainUnitOfWork(sqlite_connection)
            ).create(
                workspace_name=" Cairo controls ", period_name=" 2026-Q3 ",
                start_date="2026-07-01", end_date="2026-09-30", actor_label=" controller ",
            )
        finally:
            sqlite_connection.close()
        assert (
            result.workspace.name, result.workspace.local_first_note,
            result.period.name, result.period.start_date, result.period.end_date,
            [event.action for event in result.audit_events],
            result.audit_events[0].metadata,
            {key: value for key, value in result.audit_events[1].metadata.items() if key != "workspace_id"},
        ) == (
            sqlite_result.workspace.name, sqlite_result.workspace.local_first_note,
            sqlite_result.period.name, sqlite_result.period.start_date, sqlite_result.period.end_date,
            [event.action for event in sqlite_result.audit_events],
            sqlite_result.audit_events[0].metadata,
            {key: value for key, value in sqlite_result.audit_events[1].metadata.items() if key != "workspace_id"},
        )
        assert result.audit_events[1].metadata["workspace_id"] == result.workspace.id
        assert sqlite_result.audit_events[1].metadata["workspace_id"] == sqlite_result.workspace.id

        with PostgresDomainUnitOfWork(factory, tenant_a) as unit_of_work:
            assert unit_of_work.workspaces.get(result.workspace.id) == result.workspace
            assert unit_of_work.periods.get(result.period.id) == result.period
            assert [event.id for event in unit_of_work.audit_events.list()] == [
                result.audit_events[0].id, result.audit_events[1].id
            ]
            verification = unit_of_work.audit_events.verify()
            assert verification.ok is True and verification.checked_events == 2

        def create_parallel(index: int) -> str:
            created = WorkspacePeriodApplicationService(
                lambda: PostgresDomainUnitOfWork(factory, tenant_a)
            ).create(
                workspace_name=f"Parallel {index}", period_name="2026-Q4",
                start_date="2026-10-01", end_date="2026-12-31",
                actor_label=f"controller-{index}",
            )
            return created.workspace.id

        with ThreadPoolExecutor(max_workers=2) as executor:
            parallel_ids = list(executor.map(create_parallel, range(2)))
        assert len(set(parallel_ids)) == 2
        with PostgresDomainUnitOfWork(factory, tenant_a) as concurrent_state:
            assert len(concurrent_state.workspaces.list()) == 3
            assert [event.sequence for event in concurrent_state.audit_events.list()] == list(range(1, 7))
            concurrent_verification = concurrent_state.audit_events.verify()
            assert concurrent_verification.ok is True and concurrent_verification.checked_events == 6
        with pytest.raises(psycopg.Error, match="append-only"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.domain_audit_events SET action='tampered' "
                "WHERE tenant_id=%s AND id=%s",
                (tenant_a, result.audit_events[0].id),
            )
        with PostgresDomainUnitOfWork(factory, tenant_b) as other_tenant:
            assert other_tenant.workspaces.get(result.workspace.id) is None
            assert other_tenant.periods.get(result.period.id) is None
            assert other_tenant.audit_events.list() == []

        with PostgresDomainUnitOfWork(factory, tenant_b) as uncommitted:
            uncommitted.workspaces.create(name="Must roll back")
        with PostgresDomainUnitOfWork(factory, tenant_b) as fail_closed:
            assert fail_closed.workspaces.list() == []

        with admin.transaction():
            admin.execute(
                """
                CREATE OR REPLACE FUNCTION reconforge.reject_test_period_audit()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF NEW.action = 'period.created' THEN RAISE EXCEPTION 'synthetic audit failure'; END IF;
                  RETURN NEW;
                END; $$;
                """
            )
            admin.execute(
                "CREATE TRIGGER reject_test_period_audit BEFORE INSERT ON reconforge.domain_audit_events "
                "FOR EACH ROW EXECUTE FUNCTION reconforge.reject_test_period_audit()"
            )
        try:
            with pytest.raises(AuditLedgerError, match="Unable to append audit event"):
                WorkspacePeriodApplicationService(
                    lambda: PostgresDomainUnitOfWork(factory, tenant_b)
                ).create(
                    workspace_name="Rollback workspace", period_name="2026-Q3",
                    start_date="2026-07-01", end_date="2026-09-30", actor_label="controller",
                )
        finally:
            with admin.transaction():
                admin.execute(
                    "DROP TRIGGER IF EXISTS reject_test_period_audit ON reconforge.domain_audit_events"
                )
                admin.execute("DROP FUNCTION IF EXISTS reconforge.reject_test_period_audit()")
        with PostgresDomainUnitOfWork(factory, tenant_b) as rolled_back:
            assert rolled_back.workspaces.list() == []
            assert rolled_back.periods.list() == []
            assert rolled_back.audit_events.list() == []
    finally:
        admin.close()
