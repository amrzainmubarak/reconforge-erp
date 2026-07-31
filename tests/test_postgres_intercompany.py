from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.intercompany import IntercompanyApplicationService
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
from reconforge.infrastructure.postgres_intercompany import (
    POSTGRES_INTERCOMPANY_SCHEMA_SQL,
    PostgresIntercompanyError,
    PostgresIntercompanyRepository,
    install_postgres_intercompany_schema,
)
from reconforge.infrastructure.postgres_journals import install_postgres_journal_schema
from reconforge.infrastructure.sqlite_intercompany import SQLiteIntercompanyRepository
from reconforge.platform.common import PlatformError


class _Transaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.rolled_back = exc_type is not None


class _Connection:
    def __init__(self, *, workspace_exists: bool, fail_outbox: bool = False) -> None:
        self.workspace_exists = workspace_exists
        self.fail_outbox = fail_outbox
        self.rowcount = 0
        self.transactions: list[_Transaction] = []
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def transaction(self) -> _Transaction:
        transaction = _Transaction()
        self.transactions.append(transaction)
        return transaction

    def execute(
        self, query: str, parameters: tuple[object, ...] | None = None
    ) -> _Connection:
        self.executed.append((query, parameters))
        if self.fail_outbox and "INSERT INTO reconforge.outbox_events" in query:
            raise RuntimeError("synthetic outbox failure")
        return self

    def fetchone(self) -> tuple[str] | None:
        if "SELECT id FROM reconforge.domain_workspaces" in self.executed[-1][0]:
            return ("workspace-finance",) if self.workspace_exists else None
        return None


def _source(path: Path) -> Path:
    path.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,amount,currency,reference\n"
        "IC-1,2026-08,A,B,100.000,USD,REF-A\n"
        "IC-2,2026-08,B,A,-100.000,USD,REF-A\n"
        "IC-3,2026-08,A,B,10.125,USD,REF-B\n",
        encoding="utf-8",
    )
    return path


def test_postgres_intercompany_schema_is_exact_tenant_scoped_and_complete() -> None:
    assert "intercompany_transactions" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "intercompany_cases" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "amount NUMERIC NOT NULL" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "amount_decimal TEXT NOT NULL" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "imbalance_amount NUMERIC NOT NULL" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "FOREIGN KEY (tenant_id,workspace_id)" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_INTERCOMPANY_SCHEMA_SQL
    assert " REAL " not in POSTGRES_INTERCOMPANY_SCHEMA_SQL


def test_postgres_intercompany_missing_workspace_rolls_back_before_import(tmp_path: Path) -> None:
    connection = _Connection(workspace_exists=False)
    repository = PostgresIntercompanyRepository(connection, "tenant_a")

    with pytest.raises(PostgresIntercompanyError, match="workspace was not found"):
        repository.import_transactions(_source(tmp_path / "intercompany.csv"), workspace="Finance")

    assert connection.transactions[0].rolled_back is True
    assert connection.executed[0] == (
        "SELECT set_config('app.tenant_id', %s, true)", ("tenant_a",)
    )
    assert all(
        "INSERT INTO reconforge.intercompany_transactions" not in query
        for query, _ in connection.executed
    )


def test_postgres_intercompany_import_rolls_back_prior_write_when_outbox_fails(
    tmp_path: Path,
) -> None:
    connection = _Connection(workspace_exists=True, fail_outbox=True)
    repository = PostgresIntercompanyRepository(connection, "tenant_a")

    with pytest.raises(PostgresIntercompanyError, match="operation failed"):
        repository.import_transactions(_source(tmp_path / "intercompany.csv"), workspace="Finance")

    assert connection.transactions[0].rolled_back is True
    assert sum(
        "INSERT INTO reconforge.intercompany_transactions" in query
        for query, _ in connection.executed
    ) == 3
    assert any("INSERT INTO reconforge.outbox_events" in query for query, _ in connection.executed)


def test_postgres_intercompany_rejects_binary_float_tolerance_before_transaction() -> None:
    connection = _Connection(workspace_exists=True)
    repository = PostgresIntercompanyRepository(connection, "tenant_a")

    with pytest.raises(PlatformError, match="Could not parse financial amount"):
        repository.match(tolerance=0.1)

    assert connection.transactions == []


def test_postgres_intercompany_missing_settlement_has_no_evidence_effect() -> None:
    connection = _Connection(workspace_exists=True)
    repository = PostgresIntercompanyRepository(connection, "tenant_a")

    with pytest.raises(PlatformError, match="case not found"):
        repository.settle("ICC-missing")

    assert connection.transactions[0].rolled_back is True
    assert all("INSERT INTO reconforge.outbox_events" not in query for query, _ in connection.executed)
    assert all("domain_audit_events" not in query for query, _ in connection.executed)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_intercompany_matches_sqlite_and_enforces_rls(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "intercompany_a_" + uuid4().hex[:8]
    tenant_b = "intercompany_b_" + uuid4().hex[:8]
    source = _source(tmp_path / "intercompany.csv")
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            install_postgres_journal_schema(admin)
            install_postgres_intercompany_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.domain_workspaces,"
                f"reconforge.domain_periods,reconforge.domain_audit_ledger_state,"
                f"reconforge.domain_audit_events,reconforge.outbox_events,"
                f"reconforge.control_exceptions,reconforge.intercompany_transactions,"
                f"reconforge.intercompany_cases TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            WorkspacePeriodApplicationService(
                lambda tenant=tenant: PostgresDomainUnitOfWork(factory, tenant)
            ).create(
                workspace_name="Finance", period_name="2026-08",
                start_date="2026-08-01", end_date="2026-08-31",
                actor_label="controller",
            )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            service = IntercompanyApplicationService(
                PostgresIntercompanyRepository(connection, tenant_a)
            )
            assert service.import_transactions(source, workspace="Finance").imported_rows == 3
            assert service.match(workspace="Finance", period_name="2026-08", tolerance="0.01") == 1
            pg_case = service.cases(status="Open")[0]
            assert pg_case["imbalance_amount_decimal"] == "10.125"
            assert connection.execute(
                "SELECT COUNT(*) FROM reconforge.control_exceptions "
                "WHERE tenant_id=%s AND workspace_id=%s AND source_type='intercompany'",
                (tenant_a, pg_case["workspace_id"]),
            ).fetchone()[0] == 1
            settled = service.settle(
                str(pg_case["id"]), dispute_owner="controller", evidence_note="Synthetic evidence"
            )
            assert settled["status"] == "Resolved"
            assert connection.execute(
                "SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0] >= 3
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            isolated = IntercompanyApplicationService(
                PostgresIntercompanyRepository(connection, tenant_b)
            )
            assert isolated.cases() == []

        sqlite_path = tmp_path / "intercompany-parity.db"
        run_migrations(sqlite_path)
        sqlite = connect(sqlite_path, require_exists=True)
        try:
            local = IntercompanyApplicationService(SQLiteIntercompanyRepository(sqlite))
            local.import_transactions(source, workspace="Finance")
            assert local.match(workspace="Finance", period_name="2026-08", tolerance="0.01") == 1
            local_case = local.cases(status="Open")[0]
            assert (
                pg_case["period_name"], pg_case["entity_code"], pg_case["counterparty_code"],
                pg_case["reference"], pg_case["imbalance_amount_decimal"], pg_case["currency"],
            ) == (
                local_case["period_name"], local_case["entity_code"],
                local_case["counterparty_code"], local_case["reference"],
                local_case["imbalance_amount_decimal"], local_case["currency"],
            )
        finally:
            sqlite.close()
    finally:
        admin.close()
