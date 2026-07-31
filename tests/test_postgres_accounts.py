from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.accounts import AccountReconciliationRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_accounts import (
    POSTGRES_ACCOUNTS_SCHEMA_SQL,
    PostgresAccountReconciliationRepository,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0028_postgres_accounts.py"
    spec = importlib.util.spec_from_file_location("migration_0028", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_accounts_schema_has_exact_tenant_aggregate_and_forced_rls() -> None:
    tables = (
        "account_reconciliation_templates", "trial_balance_rows",
        "account_reconciliation_records", "account_reconciliation_items",
        "account_reconciliation_transitions",
    )
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_ACCOUNTS_SCHEMA_SQL
        assert f"'{table}'" in POSTGRES_ACCOUNTS_SCHEMA_SQL
    assert "balance NUMERIC NOT NULL" in POSTGRES_ACCOUNTS_SCHEMA_SQL
    assert "balance_decimal TEXT NOT NULL" in POSTGRES_ACCOUNTS_SCHEMA_SQL
    assert "materiality_threshold NUMERIC NOT NULL" in POSTGRES_ACCOUNTS_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_ACCOUNTS_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_ACCOUNTS_SCHEMA_SQL


def test_accounts_schema_guards_lifecycle_sod_history_and_financial_immutability() -> None:
    schema = POSTGRES_ACCOUNTS_SCHEMA_SQL
    assert "invalid account reconciliation status transition" in schema
    assert "reviewing an account reconciliation requires separation of duties" in schema
    assert "prepared account reconciliation financial fields are immutable" in schema
    assert "completed account reconciliations are immutable" in schema
    assert "account reconciliation transition evidence is append only" in schema
    assert "transition evidence must match the current reconciliation status" in schema


def test_accounts_migration_is_linear_and_child_first() -> None:
    migration = _migration()
    assert migration.revision == "0028_postgres_accounts"
    assert migration.down_revision == "0027_postgres_inventory_planning"
    source = (ROOT / "alembic/versions/0028_postgres_accounts.py").read_text(encoding="utf-8")
    assert source.index("account_reconciliation_transitions CASCADE") < source.index(
        "account_reconciliation_records CASCADE"
    )
    assert source.index("account_reconciliation_items CASCADE") < source.index(
        "account_reconciliation_records CASCADE"
    )


def test_accounts_adapter_matches_all_eleven_application_signatures() -> None:
    methods = [
        name for name, value in vars(AccountReconciliationRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(methods) == 11
    for name in methods:
        assert inspect.signature(getattr(PostgresAccountReconciliationRepository, name)) == inspect.signature(
            getattr(AccountReconciliationRepositoryProtocol, name)
        )


def test_accounts_adapter_has_bounded_ingress_transactional_evidence_and_no_external_calls() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_accounts.py").read_text(encoding="utf-8")
    assert "read_local_record_document" in source
    assert "source_checksum_sha256" in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source
    assert "FOR UPDATE" in source
    assert "Separation of duties conflict" in source
    assert "LIMIT 10000" in source
    assert "requests." not in source
    assert "httpx." not in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_accounts_exact_lifecycle_roll_forward_and_rls(tmp_path: Path) -> None:
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
    tenant_a, tenant_b = "accounts_a_" + uuid4().hex[:8], "accounts_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_ACCOUNTS_SCHEMA_SQL)
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
        trial_balance = tmp_path / "trial-balance.csv"
        trial_balance.write_text(
            "period,entity_code,account_code,account_name,balance,currency\n"
            "2026-07,EG01,1000,Cash,125000.250000000000001,USD\n",
            encoding="utf-8",
        )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            accounts = PostgresAccountReconciliationRepository(connection, tenant_a)
            template = accounts.create_template(
                account_code="1000", name="Cash review", workspace="finance", risk_rating="high",
                materiality_threshold="100.100000000000001", required_evidence="Bank statement",
                owner="owner", reviewer="reviewer", actor_label="preparer",
            )
            assert template["materiality_threshold_decimal"] == "100.100000000000001"
            imported = accounts.import_trial_balance(trial_balance, workspace="finance", actor_label="preparer")
            assert (imported.imported_rows, imported.reconciliation_records) == (1, 1)
            record = accounts.list_reconciliations(period_name="2026-07")[0]
            assert record["balance_decimal"] == "125000.250000000000001"
            assert record["currency_code"] == "USD"
            prepared = accounts.prepare(reconciliation_id=str(record["id"]), actor_label="preparer")
            assert prepared["status"] == "Prepared"
            accounts.submit(str(record["id"]), actor_label="preparer")
            with pytest.raises(PlatformError, match="Separation of duties"):
                accounts.review(str(record["id"]), actor_label="preparer")
            reviewed = accounts.review(str(record["id"]), reviewer="reviewer", actor_label="reviewer")
            assert reviewed["status"] == "Reviewed"
            completed = accounts.complete(str(record["id"]), actor_label="controller")
            assert completed["status"] == "Complete"
            transitions = connection.execute(
                "SELECT from_status,to_status,actor_label FROM reconforge.account_reconciliation_transitions WHERE tenant_id=%s AND reconciliation_id=%s ORDER BY transition_sequence",
                (tenant_a, record["id"]),
            ).fetchall()
            assert [tuple(row) for row in transitions] == [
                ("Draft", "Prepared", "preparer"),
                ("Prepared", "In Review", "preparer"),
                ("In Review", "Reviewed", "reviewer"),
                ("Reviewed", "Complete", "controller"),
            ]
            assert accounts.roll_forward(
                from_period="2026-07", to_period="2026-08", workspace="finance", actor_label="preparer"
            ) == 1
            forwarded = accounts.list_reconciliations(period_name="2026-08")[0]
            assert (forwarded["status"], forwarded["balance_decimal"], forwarded["risk_rating"]) == (
                "Draft", "0", "high",
            )
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0]
            outbox_count = connection.execute(
                "SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0]
            assert audit_count == outbox_count == 7
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            accounts_b = PostgresAccountReconciliationRepository(connection, tenant_b)
            assert accounts_b.list_reconciliations() == []
            with pytest.raises(PlatformError, match="not found"):
                accounts_b.get_reconciliation(str(record["id"]))
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
