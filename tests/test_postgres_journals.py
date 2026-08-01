from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.journals import JournalControlApplicationService
from reconforge.db import connect, run_migrations
from reconforge.domain.journal_controls import JournalPolicyError, evaluate_journal_policies, journal_threshold
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
from reconforge.infrastructure.postgres_journals import (
    POSTGRES_JOURNAL_SCHEMA_SQL,
    PostgresJournalControlError,
    PostgresJournalControlRepository,
    install_postgres_journal_schema,
)
from reconforge.infrastructure.sqlite_journals import SQLiteJournalControlRepository


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


def test_postgres_journal_schema_is_exact_tenant_scoped_and_migratable() -> None:
    assert "amount NUMERIC NOT NULL" in POSTGRES_JOURNAL_SCHEMA_SQL
    assert "amount_decimal TEXT NOT NULL" in POSTGRES_JOURNAL_SCHEMA_SQL
    assert " REAL " not in POSTGRES_JOURNAL_SCHEMA_SQL
    assert POSTGRES_JOURNAL_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 1
    assert "FOREACH table_name" in POSTGRES_JOURNAL_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_JOURNAL_SCHEMA_SQL
    assert "control_exceptions" in POSTGRES_JOURNAL_SCHEMA_SQL
    assert "outbox_events" not in POSTGRES_JOURNAL_SCHEMA_SQL


def test_shared_journal_policy_is_exact_deterministic_and_rejects_binary_float() -> None:
    row = {
        "posting_date": "2026-09-05", "is_manual": True, "reference": "", "approver": "",
        "amount_decimal": "1000.00", "account_code": "9999",
    }
    policies = evaluate_journal_policies(
        row, period_end="2026-08-31", high_value_threshold=journal_threshold("1000.00"),
        high_risk_accounts={"9999"},
    )
    assert [code for code, _, _ in policies] == [
        "MANUAL_JOURNAL", "POST_PERIOD", "WEEKEND_POSTING", "MISSING_REFERENCE",
        "MISSING_APPROVER", "HIGH_VALUE", "HIGH_RISK_ACCOUNT",
    ]
    with pytest.raises(JournalPolicyError, match="invalid"):
        journal_threshold(1000.0)


def test_postgres_journal_missing_workspace_rolls_back_without_import(tmp_path: Path) -> None:
    source = tmp_path / "journals.csv"
    source.write_text("journal_id,amount\nJ-1,100.00\n", encoding="utf-8")
    connection = _MissingWorkspaceConnection()
    repository = PostgresJournalControlRepository(connection, "tenant_a")

    with pytest.raises(PostgresJournalControlError, match="workspace was not found"):
        repository.import_journals(source, workspace="Finance")

    assert connection.transactions[0].rolled_back is True
    assert connection.executed[0] == (
        "SELECT set_config('app.tenant_id', %s, true)", ("tenant_a",),
    )
    assert all("INSERT INTO reconforge.journal_entries" not in query for query, _ in connection.executed)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_journals_match_sqlite_and_enforce_rls(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "journal_a_" + uuid4().hex[:8]
    tenant_b = "journal_b_" + uuid4().hex[:8]
    source = tmp_path / "journals.csv"
    source.write_text(
        "journal_id,period_name,entity_code,posting_date,account_code,amount,currency,reference,approver,is_manual\n"
        "J-1,2026-08,EG01,2026-09-05,9999,1000.00,USD,,,true\n",
        encoding="utf-8",
    )
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            install_postgres_journal_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.domain_workspaces,"
                f"reconforge.domain_periods,reconforge.domain_audit_ledger_state,"
                f"reconforge.domain_audit_events,reconforge.outbox_events,"
                f"reconforge.journal_entries,reconforge.journal_exceptions,"
                f"reconforge.control_exceptions TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)", (tenant_a, tenant_a, tenant_b, tenant_b))
        for tenant in (tenant_a, tenant_b):
            from reconforge.application.workspace_periods import WorkspacePeriodApplicationService

            WorkspacePeriodApplicationService(lambda tenant=tenant: PostgresDomainUnitOfWork(factory, tenant)).create(
                workspace_name="Finance", period_name="2026-08", start_date="2026-08-01",
                end_date="2026-08-31", actor_label="controller",
            )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            service = JournalControlApplicationService(PostgresJournalControlRepository(connection, tenant_a))
            assert service.import_journals(source, workspace="Finance").imported_rows == 1
            pg_count = service.policy_run(
                workspace="Finance", period_name="2026-08", period_end="2026-08-31",
                high_value_threshold="1000.00", high_risk_accounts="9999", actor_label="reviewer",
            )
            pg_codes = {item["policy_code"] for item in service.exceptions(period_name="2026-08")}
            pg_report = service.report()
            assert connection.execute("SELECT COUNT(*) FROM reconforge.control_exceptions WHERE tenant_id=%s", (tenant_a,)).fetchone()[0] == pg_count
            assert connection.execute("SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant_a,)).fetchone()[0] >= 2
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            isolated = JournalControlApplicationService(PostgresJournalControlRepository(connection, tenant_b))
            assert isolated.report() == {"journal_entries": 0, "journal_exceptions": 0, "high_risk_exceptions": 0}
            assert isolated.exceptions() == []

        sqlite_path = tmp_path / "journal-parity.db"
        run_migrations(sqlite_path)
        sqlite = connect(sqlite_path, require_exists=True)
        try:
            sqlite_service = JournalControlApplicationService(SQLiteJournalControlRepository(sqlite))
            sqlite_service.import_journals(source, workspace="Finance")
            sqlite_count = sqlite_service.policy_run(
                workspace="Finance", period_name="2026-08", period_end="2026-08-31",
                high_value_threshold="1000.00", high_risk_accounts="9999",
            )
            sqlite_codes = {item["policy_code"] for item in sqlite_service.exceptions(period_name="2026-08")}
            assert pg_count == sqlite_count == 7
            assert pg_codes == sqlite_codes
            assert pg_report == sqlite_service.report()
        finally:
            sqlite.close()
    finally:
        admin.close()
