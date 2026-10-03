"""Forward-only AR schema leaves historical minor units explicitly unresolved."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.receivables_policy_schema import SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL
from reconforge.infrastructure.sqlite_receivables import SQLiteReceivablesRepository
from reconforge.platform.common import ensure_workspace
from tests.test_alembic_postgres import isolated_postgres_migration_dsn

__all__ = ["isolated_postgres_migration_dsn"]


def test_frozen_0099_matches_current_installer() -> None:
    import ast

    from reconforge.infrastructure.receivables_policy_schema import POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL

    tree = ast.parse(Path("alembic/versions/0099_postgres_receivables_policy.py").read_text())
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
    assert values["revision"] == "0099_pg_receivables_policy"
    assert values["down_revision"] == "0098_pg_finance_posting"
    assert values["UPGRADE_SQL"] == POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL


def test_live_empty_0099_downgrade_and_retained_policy_refusal(isolated_postgres_migration_dsn: str) -> None:
    import psycopg
    from alembic.config import Config
    from sqlalchemy.exc import DBAPIError

    from alembic import command

    config = Config("alembic.ini")
    command.upgrade(config, "0099_pg_receivables_policy")
    command.downgrade(config, "0098_pg_finance_posting")
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        assert admin.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='reconforge' AND table_name='ar_customers' AND column_name='currency_precision'").fetchone() == (0,)
    command.upgrade(config, "0099_pg_receivables_policy")
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES('refuse','Synthetic')")
        admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES('refuse','work','Synthetic')")
        admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('refuse','JPY','Synthetic',0)")
        policy, _ = FinancePolicyStore(admin, tenant_id="refuse").capture(workspace_id="work", currency_code="JPY", minor_units=0, actor_label="synthetic")
        admin.execute("INSERT INTO reconforge.ar_customers(tenant_id,id,workspace_id,customer_code,name,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest) VALUES('refuse','customer','work','CUS','Synthetic','JPY',%s,%s,%s,%s)", policy.values())
    with pytest.raises(DBAPIError, match="AR policy downgrade refused"):
        command.downgrade(config, "0098_pg_finance_posting")
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone() == ("0099_pg_receivables_policy",)
        assert admin.execute("SELECT currency_precision FROM reconforge.ar_customers WHERE tenant_id='refuse'").fetchone() == (0,)


def legacy_customer(connection: sqlite3.Connection, currency: str = "USD") -> None:
    workspace = ensure_workspace(connection, "default")
    connection.execute("INSERT INTO ar_customers(id,workspace_id,customer_code,name,currency_code,credit_limit_minor,created_at,updated_at) VALUES('legacy',?,'LEGACY','Legacy',?,1234,'2026-01-01','2026-01-01')", (workspace, currency))
    connection.commit()


@pytest.mark.parametrize("currency", ["USD", "ΔΕΖ"])
def test_additive_policy_upgrade_keeps_legacy_identity_and_unverified_reads(tmp_path: Path, currency: str) -> None:
    path = tmp_path / "old.db"
    run_migrations(path, target_version=48)
    with closing(connect(path)) as connection:
        ensure_workspace(connection, "default")
        legacy_customer(connection, currency)
        connection.execute("INSERT INTO ar_invoices(id,workspace_id,customer_id,invoice_number,invoice_date,due_date,currency_code,subtotal_minor,tax_minor,total_minor,status,created_at,updated_at) SELECT 'legacy-invoice',workspace_id,id,'LEGACY-INVOICE','2026-01-01','2026-01-01',currency_code,1234,0,1234,'Submitted','2026-01-01','2026-01-01' FROM ar_customers WHERE id='legacy'")
        connection.commit()
        before = dict(connection.execute("SELECT * FROM ar_customers WHERE id='legacy'").fetchone())
        connection.executescript(SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL)
        after = SQLiteReceivablesRepository(connection).get_customer("legacy")
        assert {key: after[key] for key in before} == before
        assert after["monetary_policy"]["status"] == "unverified"
        assert after["monetary_policy"]["currency_code"] == currency
        assert after["monetary_policy"]["precision"] is None
        with pytest.raises(sqlite3.IntegrityError, match="Legacy AR monetary policy"):
            connection.execute("UPDATE ar_customers SET credit_limit_minor=9999 WHERE id='legacy'")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="Legacy AR monetary policy"):
            connection.execute("UPDATE ar_invoices SET status='Approved' WHERE id='legacy-invoice'")
        connection.rollback()


def test_new_rows_require_complete_policy_and_retained_identity_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    run_migrations(path, target_version=48)
    with closing(connect(path)) as connection:
        workspace = ensure_workspace(connection, "default")
        connection.commit()
        connection.executescript(SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL)
        with pytest.raises(sqlite3.IntegrityError, match="verified monetary policy"):
            legacy_customer(connection)
        connection.rollback()
        policy, _ = FinancePolicyStore(connection).capture(workspace_id=workspace, currency_code="USD", minor_units=2, actor_label="synthetic")
        connection.execute("INSERT INTO ar_customers(id,workspace_id,customer_code,name,currency_code,credit_limit_minor,created_at,updated_at,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest) VALUES('captured',?,'CAPTURED','Captured','USD',1234,'2026-01-01','2026-01-01',?,?,?,?)", (workspace, *policy.values()))
        connection.commit()
        record = SQLiteReceivablesRepository(connection).get_customer("captured")
        assert record["monetary_policy"]["status"] == "captured"
        for statement in (
            "UPDATE ar_customers SET currency_precision=3 WHERE id='captured'",
            "UPDATE ar_customers SET currency_registry_version='forged' WHERE id='captured'",
            "UPDATE ar_customers SET currency_registry_digest=NULL WHERE id='captured'",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable|does not match retained snapshot"):
                connection.execute(statement)
            connection.rollback()


def test_capture_absent_master_requires_explicit_opt_in(tmp_path: Path) -> None:
    path = tmp_path / "capture.db"
    run_migrations(path, target_version=48)
    with closing(connect(path)) as connection:
        ensure_workspace(connection, "default")
        with pytest.raises(ValueError, match="master precision"):
            FinancePolicyStore(connection).capture(workspace_id="default", currency_code="USD", minor_units=None, actor_label="synthetic")


def test_live_pg_policy_upgrade_preserves_legacy_and_guards_new_rows(isolated_postgres_migration_dsn: str) -> None:
    import psycopg
    from alembic.config import Config

    from alembic import command
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
    from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
    from reconforge.infrastructure.receivables_policy_schema import POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires synthetic nonowner PostgreSQL app DSN; PROD033 acceptance reviewed 2026-10-03")
    command.upgrade(Config("alembic.ini"), "0098_pg_finance_posting")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES('ar_policy','Synthetic')")
        admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES('ar_policy','workspace','Synthetic')")
        admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('ar_policy','USD','Synthetic dollar',2)")
        admin.execute("INSERT INTO reconforge.ar_customers(tenant_id,id,workspace_id,customer_code,name,currency_code,credit_limit_minor) VALUES('ar_policy','legacy','workspace','LEGACY','Legacy','USD',1234)")
        admin.execute("INSERT INTO reconforge.ar_invoices(tenant_id,id,workspace_id,customer_id,invoice_number,invoice_date,due_date,currency_code,subtotal_minor,tax_minor,total_minor,status) VALUES('ar_policy','legacy-invoice','workspace','legacy','LEGACY-INVOICE','2026-01-01','2026-01-01','USD',1234,0,1234,'Submitted')")
        admin.execute(POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL)
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
    factory = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False))
    with PostgresTenantBoundary(factory).transaction("ar_policy") as connection:
        repo = PostgresReceivablesRepository(connection, "ar_policy")
        legacy = repo.get_customer("legacy")
        assert legacy["credit_limit_minor"] == 1234 and legacy["monetary_policy"]["status"] == "unverified"
        with pytest.raises(psycopg.errors.RaiseException, match="verified monetary policy"), connection.transaction():
            connection.execute("INSERT INTO reconforge.ar_customers(tenant_id,id,workspace_id,customer_code,name,currency_code) VALUES('ar_policy','missing','workspace','MISSING','Missing','USD')")
        policy, _ = FinancePolicyStore(connection, tenant_id="ar_policy").capture(workspace_id="workspace", currency_code="USD", minor_units=2, actor_label="synthetic")
        connection.execute("INSERT INTO reconforge.ar_customers(tenant_id,id,workspace_id,customer_code,name,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest) VALUES('ar_policy','captured','workspace','CAPTURED','Captured','USD',%s,%s,%s,%s)", policy.values())
        assert repo.get_customer("captured")["monetary_policy"]["status"] == "captured"
        with pytest.raises(psycopg.errors.RaiseException, match="immutable|does not match retained snapshot"), connection.transaction():
            connection.execute("UPDATE reconforge.ar_customers SET currency_precision=3 WHERE tenant_id='ar_policy' AND id='captured'")
        with pytest.raises(psycopg.errors.RaiseException, match="Legacy AR"), connection.transaction():
            connection.execute("UPDATE reconforge.ar_customers SET credit_limit_minor=9999 WHERE tenant_id='ar_policy' AND id='legacy'")
        with pytest.raises(psycopg.errors.RaiseException, match="Legacy AR"), connection.transaction():
            connection.execute("UPDATE reconforge.ar_invoices SET status='Approved' WHERE tenant_id='ar_policy' AND id='legacy-invoice'")
