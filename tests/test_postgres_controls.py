from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.controls import ControlTestingApplicationService
from reconforge.application.workspace_periods import WorkspacePeriodApplicationService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_controls import (
    POSTGRES_CONTROL_TESTING_SCHEMA_SQL,
    PostgresControlTestingError,
    PostgresControlTestingRepository,
    install_postgres_control_testing_schema,
)
from reconforge.infrastructure.postgres_domain import PostgresDomainUnitOfWork, install_postgres_domain_schema
from reconforge.infrastructure.postgres_journals import install_postgres_journal_schema
from reconforge.infrastructure.sqlite_controls import SQLiteControlTestingRepository


class _Transaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.rolled_back = exc_type is not None


class _MissingWorkspaceConnection:
    def __init__(self) -> None:
        self.transactions: list[_Transaction] = []
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def transaction(self) -> _Transaction:
        transaction = _Transaction()
        self.transactions.append(transaction)
        return transaction

    def execute(self, query: str, parameters: tuple[object, ...] | None = None) -> _MissingWorkspaceConnection:
        self.executed.append((query, parameters))
        return self

    def fetchone(self) -> None:
        return None


class _FailingOutboxConnection(_MissingWorkspaceConnection):
    def execute(
        self, query: str, parameters: tuple[object, ...] | None = None
    ) -> _FailingOutboxConnection:
        self.executed.append((query, parameters))
        if "INSERT INTO reconforge.outbox_events" in query:
            raise RuntimeError("synthetic outbox failure")
        return self

    def fetchone(self) -> tuple[str] | None:
        query = self.executed[-1][0]
        if "SELECT id FROM reconforge.domain_workspaces" in query:
            return ("workspace-finance",)
        return None


def test_postgres_control_schema_is_tenant_scoped_and_complete() -> None:
    for table in ("control_library", "control_test_plans", "control_test_results", "remediation_plans"):
        assert table in POSTGRES_CONTROL_TESTING_SCHEMA_SQL
    assert "CHECK (sample_size >= 0)" in POSTGRES_CONTROL_TESTING_SCHEMA_SQL
    assert "FOREIGN KEY (tenant_id,workspace_id)" in POSTGRES_CONTROL_TESTING_SCHEMA_SQL
    assert "FOREACH table_name" in POSTGRES_CONTROL_TESTING_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_CONTROL_TESTING_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_CONTROL_TESTING_SCHEMA_SQL
    assert " REAL " not in POSTGRES_CONTROL_TESTING_SCHEMA_SQL


def test_postgres_control_missing_workspace_rolls_back_before_import(tmp_path: Path) -> None:
    source = tmp_path / "controls.csv"
    source.write_text("control_code,name\nC-1,Cash control\n", encoding="utf-8")
    connection = _MissingWorkspaceConnection()
    repository = PostgresControlTestingRepository(connection, "tenant_a")

    with pytest.raises(PostgresControlTestingError, match="workspace was not found"):
        repository.import_library(source, workspace="Finance")

    assert connection.transactions[0].rolled_back is True
    assert connection.executed[0] == ("SELECT set_config('app.tenant_id', %s, true)", ("tenant_a",))
    assert all("INSERT INTO reconforge.control_library" not in query for query, _ in connection.executed)


def test_postgres_control_import_rolls_back_prior_writes_when_outbox_fails(tmp_path: Path) -> None:
    source = tmp_path / "controls.csv"
    source.write_text("control_code,name\nC-1,Cash control\n", encoding="utf-8")
    connection = _FailingOutboxConnection()
    repository = PostgresControlTestingRepository(connection, "tenant_a")

    with pytest.raises(PostgresControlTestingError, match="operation failed"):
        repository.import_library(source, workspace="Finance")

    assert connection.transactions[0].rolled_back is True
    library_insert = next(
        parameters
        for query, parameters in connection.executed
        if "INSERT INTO reconforge.control_library" in query
    )
    assert library_insert is not None
    assert library_insert[0] == "tenant_a"
    assert str(library_insert[1]).startswith("CTRL-")
    assert library_insert[2] == "workspace-finance"
    assert any("INSERT INTO reconforge.outbox_events" in query for query, _ in connection.executed)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_controls_match_sqlite_and_enforce_rls(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "controls_a_" + uuid4().hex[:8]
    tenant_b = "controls_b_" + uuid4().hex[:8]
    source = tmp_path / "controls.csv"
    source.write_text(
        "control_code,name,owner,frequency,risk_rating\n"
        "C-01,Cash review,controller,monthly,high\n"
        "C-02,Access review,security,quarterly,medium\n",
        encoding="utf-8",
    )
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            install_postgres_journal_schema(admin)
            install_postgres_control_testing_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.domain_workspaces,"
                f"reconforge.domain_periods,reconforge.domain_audit_ledger_state,"
                f"reconforge.domain_audit_events,reconforge.outbox_events,reconforge.control_exceptions,"
                f"reconforge.control_library,reconforge.control_test_plans,"
                f"reconforge.control_test_results,reconforge.remediation_plans TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            WorkspacePeriodApplicationService(lambda tenant=tenant: PostgresDomainUnitOfWork(factory, tenant)).create(
                workspace_name="Finance", period_name="2026-08", start_date="2026-08-01",
                end_date="2026-08-31", actor_label="controller",
            )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            service = ControlTestingApplicationService(PostgresControlTestingRepository(connection, tenant_a))
            assert service.import_library(source, workspace="Finance").imported_rows == 2
            assert service.plan_tests(period_name="2026-08", workspace="Finance", sample_size=5) == 2
            plans = service.list_plans(period_name="2026-08")
            result = service.record_result(
                plan_id=str(plans[0]["id"]), result_status="Completed",
                effectiveness_status="Ineffective", note="Synthetic test",
            )
            remediation = service.remediation(
                source_type="control_test", source_id=str(result["id"]), action_plan="Retest access",
                owner="controller", target_date="2026-09-15",
            )
            pg_report = service.report()
            assert remediation["status"] == "Open"
            assert connection.execute(
                "SELECT COUNT(*) FROM reconforge.control_exceptions WHERE tenant_id=%s AND workspace_id=%s",
                (tenant_a, plans[0]["workspace_id"]),
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0] >= 4
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            isolated = ControlTestingApplicationService(PostgresControlTestingRepository(connection, tenant_b))
            assert isolated.report() == {
                "controls": 0, "test_plans": 0, "test_results": 0, "ineffective_results": 0,
            }
            assert isolated.list_plans() == []

        sqlite_path = tmp_path / "controls-parity.db"
        run_migrations(sqlite_path)
        sqlite = connect(sqlite_path, require_exists=True)
        try:
            local = ControlTestingApplicationService(SQLiteControlTestingRepository(sqlite))
            local.import_library(source, workspace="Finance")
            local.plan_tests(period_name="2026-08", workspace="Finance", sample_size=5)
            local_plan = local.list_plans(period_name="2026-08")[0]
            local.record_result(
                plan_id=str(local_plan["id"]), result_status="Completed",
                effectiveness_status="Ineffective", note="Synthetic test",
            )
            assert pg_report == local.report() == {
                "controls": 2, "test_plans": 2, "test_results": 1, "ineffective_results": 1,
            }
        finally:
            sqlite.close()
    finally:
        admin.close()
