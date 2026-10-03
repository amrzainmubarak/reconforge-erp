"""Live policy retention on migrated, nonowner, tenant-scoped PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_master_data import (
    PostgresMasterDataRepository,
    PostgresMasterDataValidationError,
)
from reconforge.platform.common import PlatformError
from reconforge.utils.money import CurrencyRegistry, CurrencySpec
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


def _config() -> Any:
    from alembic.config import Config

    return Config(str(Path("alembic.ini").resolve()))


def _seed(connection: Any, tenant: str) -> None:
    masters = PostgresMasterDataRepository(connection)
    masters.upsert_currency(tenant_id=tenant, code="EGP", name="Synthetic EGP", minor_units=2)
    masters.upsert_currency(tenant_id=tenant, code="USD", name="Synthetic USD", minor_units=2)
    connection.execute(
        "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,'workspace','Finance'),(%s,'sibling','Sibling')",
        (tenant, tenant),
    )
    connection.execute(
        "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) "
        "VALUES (%s,'org','ORG','Synthetic','EGP','workspace')", (tenant,),
    )
    masters.upsert_legal_entity(
        tenant_id=tenant, organization_id="org", entity_id="entity", entity_code="ENTITY",
        name="Synthetic entity", currency_code="EGP",
    )
    connection.execute(
        "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) "
        "VALUES (%s,'period','2026-07','2026-07-01','2026-07-31',2026,7,'workspace')", (tenant,),
    )
    masters.bind_currency_registry(tenant_id=tenant, workspace="Finance")
    finance = PostgresFinanceCoreRepository(connection, tenant)
    finance.upsert_chart(chart_code="DEFAULT", name="Default", workspace="Finance", organization_code="ORG")
    for code, account_type, balance in (("CASH", "Asset", "Debit"), ("CAPITAL", "Equity", "Credit")):
        finance.upsert_account(account_code=code, name=code, workspace="Finance", account_type=account_type, normal_balance=balance)
    finance.upsert_journal(journal_code="GENERAL", name="General", organization_code="ORG", currency_code="EGP", workspace="Finance")


def _entry(finance: PostgresFinanceCoreRepository, number: str = "ENTRY/1") -> dict[str, Any]:
    return finance.create_entry(
        entry_number=number, organization_code="ORG", entity_code="ENTITY", period_id="period",
        journal_code="GENERAL", posting_date="2026-07-28", description="Synthetic entry", workspace="Finance",
        actor_label="maker", lines=({"account_code": "CASH", "debit": "100.00"}, {"account_code": "CAPITAL", "credit": "100.00"}),
    )


def test_live_currency_policy_preserves_money_scope_replay_and_populated_downgrade(
    isolated_postgres_migration_dsn: str,
) -> None:
    import psycopg
    from sqlalchemy.exc import DBAPIError

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    CurrencyRegistry.reset_to_bundled()
    command.upgrade(_config(), "head")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    factory = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    try:
        with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
            role = psycopg.sql.Identifier(params["user"])
            admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
            admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES ('policy_a','A'),('policy_b','B')")
        for tenant in ("policy_a", "policy_b"):
            with boundary.transaction(tenant) as connection:
                assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
                _seed(connection, tenant)
        with boundary.transaction("policy_a") as connection:
            finance = PostgresFinanceCoreRepository(connection, "policy_a")
            first = _entry(finance)
            original_digest = first["currency_registry_digest"]
            # A concurrent metadata writer must wait for the captured-policy reader.
            with pytest.raises(psycopg.errors.LockNotAvailable), boundary.transaction("policy_a") as contender:
                contender.execute("SET LOCAL lock_timeout='100ms'")
                PostgresMasterDataRepository(contender).upsert_currency(
                    tenant_id="policy_a", code="EGP", name="Racing precision", minor_units=3,
                )
            CurrencyRegistry.register(
                CurrencySpec(code="EGP", name="Synthetic drift", minor_units=3),
                registry_version="synthetic-live-v2", source="Synthetic verification",
            )
            assert _entry(finance)["total_debit_minor"] == 10_000
            assert _entry(finance, "ENTRY/2")["currency_registry_digest"] == original_digest
            finance.validate_entry(first["id"], reason="Independent review", actor_label="checker")
            master = PostgresMasterDataRepository(connection)
            with pytest.raises(PostgresMasterDataValidationError, match="immutable"):
                master.upsert_currency(tenant_id="policy_a", code="EGP", name="Forbidden", minor_units=3)
            with pytest.raises(PostgresMasterDataValidationError, match="immutable"):
                master.upsert_legal_entity(tenant_id="policy_a", organization_id="org", entity_id="entity", entity_code="ENTITY", name="Changed", currency_code="USD")
            master.bind_currency_registry(tenant_id="policy_a", workspace="Finance")
            assert finance.get_entry(first["id"])["total_debit"] == "100.00"
            with pytest.raises(PlatformError, match="policy_mismatch"):
                _entry(finance, "ENTRY/3")
            trial = finance.trial_balance(period_id="period", organization_code="ORG", entity_code="ENTITY", workspace="Finance")
            assert trial["totals"]["debit_minor"] == 10_000
            assert trial["totals"]["debit"] == "100.00"
        for query in (
            "UPDATE reconforge.currencies SET minor_units=3 WHERE code='EGP'",
            "UPDATE reconforge.legal_entities SET currency_code='USD' WHERE id='entity'",
            "UPDATE reconforge.currency_registry_snapshots SET snapshot_json='{}'",
            "UPDATE reconforge.finance_entries SET currency_precision=3",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"), boundary.transaction("policy_a") as connection:
                connection.execute(query)
        with boundary.transaction("policy_a") as connection:
            connection.execute("SELECT set_config('app.workspace_id','sibling',true)")
            assert connection.execute("SELECT count(*) FROM reconforge.finance_entries").fetchone()[0] == 0
            with pytest.raises(PostgresMasterDataValidationError, match="immutable"):
                PostgresMasterDataRepository(connection).upsert_currency(tenant_id="policy_a", code="EGP", name="Other workspace", minor_units=3)
        with boundary.transaction("policy_b") as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.finance_entries").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.currency_registry_snapshots WHERE tenant_id='policy_a'").fetchone()[0] == 0
        with pytest.raises(DBAPIError, match="finance policy downgrade refused"):
            command.downgrade(_config(), "0093_pg_metrics")
        with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0095_pg_finance_scope"
            assert admin.execute("SELECT count(*) FROM reconforge.finance_entries").fetchone()[0] == 2
    finally:
        CurrencyRegistry.reset_to_bundled()


def test_live_currency_policy_empty_upgrade_downgrade_replays(isolated_postgres_migration_dsn: str) -> None:
    from alembic import command

    command.upgrade(_config(), "0094_pg_finance_policy")
    command.downgrade(_config(), "0093_pg_metrics")
    command.upgrade(_config(), "0094_pg_finance_policy")


def test_live_upgrade_preserves_legacy_minor_units_without_fabricating_policy(
    isolated_postgres_migration_dsn: str,
) -> None:
    import psycopg

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    command.upgrade(_config(), "0093_pg_metrics")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    boundary = PostgresTenantBoundary(PostgresConnectionFactory(
        PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False)
    ))
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES ('legacy','Synthetic legacy')")
    with boundary.transaction("legacy") as connection:
        _seed(connection, "legacy")
        connection.execute(
            """INSERT INTO reconforge.finance_entries (
                tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,
                entry_number,posting_date,description,source_type,status,currency_code,
                total_debit_minor,total_credit_minor,created_by,created_at,updated_at
            ) SELECT tenant_id,'legacy-entry',workspace_id,id,'ORG','ENTITY','period','LEGACY',
                '2026-07-28','Retained historical entry','Manual','Draft','EGP',10000,10000,
                'historical-maker','2026-07-28T00:00:00Z','2026-07-28T00:00:00Z'
              FROM reconforge.finance_journals WHERE tenant_id='legacy'"""
        )
        for number, account, debit, credit in ((1, "CASH", 10000, 0), (2, "CAPITAL", 0, 10000)):
            connection.execute(
                """INSERT INTO reconforge.finance_entry_lines
                    (tenant_id,id,entry_id,line_number,account_id,debit_minor,credit_minor,currency_code)
                    SELECT tenant_id,%s,'legacy-entry',%s,id,%s,%s,'EGP'
                    FROM reconforge.finance_accounts WHERE tenant_id='legacy' AND account_code=%s""",
                (f"legacy-line-{number}", number, debit, credit, account),
            )
        connection.execute(
            "UPDATE reconforge.finance_entries SET status='Validated',validated_by='historical-checker',"
            "validated_at=created_at,validation_reason='Historical review' WHERE id='legacy-entry'"
        )
    command.upgrade(_config(), "0094_pg_finance_policy")
    with boundary.transaction("legacy") as connection:
        finance = PostgresFinanceCoreRepository(connection, "legacy")
        raw = finance.list_entries(workspace="Finance")[0]
        assert raw["total_debit_minor"] == 10000
        assert raw["currency_precision"] is None
        assert raw["currency_registry_digest"] is None
        for operation in (
            lambda: finance.get_entry("legacy-entry"),
            lambda: finance.void_entry("legacy-entry", reason="No inferred historical policy", actor_label="checker"),
            lambda: finance.trial_balance(workspace="Finance", organization_code="ORG", entity_code="ENTITY", period_id="period"),
        ):
            with pytest.raises(PlatformError, match="finance_currency_policy_unverified"):
                operation()
        assert connection.execute("SELECT status FROM reconforge.finance_entries WHERE id='legacy-entry'").fetchone()[0] == "Validated"
    command.downgrade(_config(), "0093_pg_metrics")
    command.upgrade(_config(), "0094_pg_finance_policy")
