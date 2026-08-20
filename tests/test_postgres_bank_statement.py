from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.bank_statement_control import (
    run_bank_statement_control_files,
    verify_bank_statement_report,
    write_bank_statement_report,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_bank_statement import (
    POSTGRES_BANK_STATEMENT_SCHEMA_SQL,
    PostgresBankStatementRepository,
)

ROOT = Path(__file__).resolve().parents[1]
STATEMENT = ROOT / "examples/bank_statement_control/statement.xml"
LEDGER = ROOT / "examples/bank_statement_control/ledger.json"


def _report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "bank-report.json"
    run = run_bank_statement_control_files(STATEMENT, LEDGER, currency="EUR", tolerance="0.01")
    write_bank_statement_report(run, report_path)
    return verify_bank_statement_report(report_path)


def test_postgres_bank_statement_schema_is_rls_immutable_and_bounded() -> None:
    assert "JSONB NOT NULL" in POSTGRES_BANK_STATEMENT_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_BANK_STATEMENT_SCHEMA_SQL
    assert "tenant_id = current_setting('app.tenant_id', true)" in POSTGRES_BANK_STATEMENT_SCHEMA_SQL
    assert "workspace_id = current_setting('app.workspace_id', true)" in POSTGRES_BANK_STATEMENT_SCHEMA_SQL
    assert "bank statement evidence is immutable" in POSTGRES_BANK_STATEMENT_SCHEMA_SQL
    assert "bank statement evidence cannot be deleted" in POSTGRES_BANK_STATEMENT_SCHEMA_SQL
    assert "secret" not in POSTGRES_BANK_STATEMENT_SCHEMA_SQL.casefold()


def test_postgres_bank_statement_migration_is_versioned_and_non_destructive() -> None:
    migration = (ROOT / "alembic/versions/0084_postgres_bank_statement_control.py").read_text(encoding="utf-8")
    assert 'revision = "0084_pg_bank_statement"' in migration
    assert 'down_revision = "0083_pg_manufacturing"' in migration
    assert "POSTGRES_BANK_STATEMENT_SCHEMA_SQL" in migration
    assert "refusing to discard bank-statement evidence" in migration
    assert "DROP TABLE IF EXISTS reconforge.bank_statement_control_runs" in migration


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_bank_statement_is_scoped_idempotent_and_append_only(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_id = "bankpg_" + uuid4().hex[:10]
    other_tenant = "bankpg_other_" + uuid4().hex[:8]
    workspace_id = "bank-workspace"
    report = _report(tmp_path)
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_connection = None
    connection = None
    try:
        admin_connection = admin_factory.connect()
        with admin_connection.transaction():
            install_postgres_rls_schema(admin_connection)
            admin_connection.execute(POSTGRES_BANK_STATEMENT_SCHEMA_SQL)
            admin_connection.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin_connection.execute(
                "GRANT SELECT, INSERT ON reconforge.bank_statement_control_runs TO " f"{app_user}"
            )
            admin_connection.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s), (%s, %s)",
                (tenant_id, tenant_id, other_tenant, other_tenant),
            )
        connection = app_factory.connect()
        repository = PostgresBankStatementRepository(connection)
        stored = repository.put_payload(report, tenant_id=tenant_id, workspace_id=workspace_id, actor_label="server-admin")
        assert repository.put_payload(
            report, tenant_id=tenant_id, workspace_id=workspace_id, actor_label="server-admin"
        ) == stored
        assert repository.get(
            decision_digest=str(report["decision_digest"]), tenant_id=tenant_id, workspace_id=workspace_id
        ) == stored
        assert repository.list(tenant_id=tenant_id, workspace_id=workspace_id) == (stored,)
        assert repository.get(
            decision_digest=str(report["decision_digest"]), tenant_id=other_tenant, workspace_id=workspace_id
        ) is None
        with pytest.raises(psycopg.Error, match="immutable"), admin_connection.transaction():
            admin_connection.execute(
                "UPDATE reconforge.bank_statement_control_runs SET prepared_by='tampered' "
                "WHERE tenant_id=%s AND workspace_id=%s",
                (tenant_id, workspace_id),
            )
    finally:
        if connection is not None:
            connection.close()
        if admin_connection is not None:
            admin_connection.close()
