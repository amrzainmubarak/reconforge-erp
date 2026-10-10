"""Empty rollback, populated refusal and least-privilege FX event dispatch."""

from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.infrastructure.postgres_operational_fx_tax_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.test_postgres_finance_scope import finance_database, isolated_postgres_migration_dsn
from tests.test_postgres_operational_fx_tax import (
    finish_fx,
    prepare_fx,
    pytestmark,
    receipt_database,
    seed_fx_runtime,
)

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "pytestmark", "receipt_database"]


def test_empty_schema_rollback_reupgrade_and_populated_evidence_refusal(receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(receipt_database[0]) as admin:
        admin.execute(DOWNGRADE_SQL)
        assert admin.execute("SELECT to_regclass('reconforge.operational_fx_sources')").fetchone()[0] is None
        admin.execute(UPGRADE_SQL)
        # Additive table recreation drops its previous ACLs; deployment's
        # explicit module grant step must accompany the restored schema.
        app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
        for table in ("operational_fx_sources", "operational_fx_plans", "operational_fx_reviews", "operational_fx_links", "operational_fx_commands"):
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO {}").format(sql.Identifier("reconforge", table), sql.Identifier(app_user)))
    runtime = seed_fx_runtime(receipt_database)
    posted = finish_fx(runtime, prepare_fx(runtime))
    with psycopg.connect(receipt_database[0]) as admin:
        with pytest.raises(psycopg.errors.RaiseException, match="refuses to discard"), admin.transaction():
            admin.execute(DOWNGRADE_SQL)
        assert admin.execute("SELECT count(*) FROM reconforge.operational_fx_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1
        assert admin.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1
    with runtime.actor("poster") as (connection, _, actor):
        evidence = PostgresOperationalFxTaxRepository(connection, runtime.tenant).plan_evidence(posted["id"], actor=actor)
        assert evidence["native_effect"]["id"] == posted["posting_effect_id"]


def test_unrelated_outbox_worker_needs_no_fx_source_read_grant(receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    runtime = seed_fx_runtime(receipt_database)
    finish_fx(runtime, prepare_fx(runtime))
    boundary = PostgresTenantBoundary(runtime.factory)
    role = "fx_unrelated_" + uuid4().hex[:12]
    app_user = psycopg.conninfo.conninfo_to_dict(runtime.factory.settings.dsn)["user"]
    event_id = "unrelated-" + uuid4().hex

    @contextmanager
    def worker() -> Any:
        with boundary.transaction(runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            yield connection

    with psycopg.connect(runtime.admin_dsn) as admin:
        # Retain populated FX history but keep its dispatches out of this
        # deliberately unrelated worker's eligible synthetic queue.
        admin.execute("UPDATE reconforge.outbox_events SET available_at='2099-01-01T00:00:00Z' WHERE tenant_id=%s", (runtime.tenant,))
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(app_user)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
        for privileges, tables in (("SELECT", "tenants"), ("SELECT,INSERT,UPDATE", "domain_audit_ledger_state"),
                                   ("SELECT,INSERT", "domain_audit_events,outbox_events,outbox_delivery_evidence")):
            admin.execute(sql.SQL("GRANT {} ON {} TO {}").format(sql.SQL(privileges),
                sql.SQL(",").join(sql.Identifier("reconforge", name) for name in tables.split(",")), sql.Identifier(role)))
        admin.execute(sql.SQL("""GRANT UPDATE(status,attempt_count,available_at,claimed_at,claimed_by,published_at,last_error,dead_lettered_at,lease_generation)
            ON reconforge.outbox_events TO {}""").format(sql.Identifier(role)))
    try:
        with worker() as connection:
            for table in ("operational_fx_sources", "operational_fx_plans", "operational_fx_reviews", "operational_fx_links", "operational_fx_commands"):
                assert connection.execute("SELECT has_table_privilege(current_user,%s,'SELECT') allowed", ("reconforge." + table,)).fetchone()["allowed"] is False
            audit = PostgresAuditEventRepository(connection, runtime.tenant).append(actor_label="restricted-worker", object_type="reconciliation_run",
                object_id="unrelated-run", action="reconciliation_completed", metadata={"synthetic": True})
            connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES(%s,%s,'reconciliation_completed','reconciliation_run','unrelated-run',%s::jsonb)""",
                (runtime.tenant, event_id, '{"audit_event_id":"' + audit.id + '"}'))
        with worker() as connection:
            claimed = PostgresOutboxRepository(connection).claim_pending(tenant_id=runtime.tenant, worker_id="restricted-worker", limit=10, lease_seconds=60)
            assert [event.id for event in claimed] == [event_id]
        with worker() as connection:
            PostgresOutboxRepository(connection).mark_published(tenant_id=runtime.tenant, event_id=event_id,
                worker_id="restricted-worker", lease_generation=claimed[0].lease_generation)
        with worker() as connection:
            assert connection.execute("SELECT status FROM reconforge.outbox_events WHERE tenant_id=%s AND event_id=%s", (runtime.tenant, event_id)).fetchone()["status"] == "Published"
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="operational_fx_plans"), worker() as connection:
            connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES(%s,%s,'operational_fx_prepared','operational_finance',%s,'{}'::jsonb)""", (runtime.tenant, "reserved-" + uuid4().hex, "FX1-" + uuid4().hex))
    finally:
        with psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_legacy_customer_and_financial_master_maintenance_needs_no_fx_read_grant(finance_database: Any) -> None:
    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        for table in ("operational_fx_sources", "operational_fx_plans", "operational_fx_reviews", "operational_fx_links", "operational_fx_commands"):
            assert connection.execute("SELECT has_table_privilege(current_user,%s,'SELECT')", ("reconforge." + table,)).fetchone()[0] is False
        native = PostgresReceivablesRepository(connection, "finance_scope")
        customer = native.upsert_customer(customer_code="ORDINARY", name="Ordinary customer", currency_code="EGP", credit_limit_minor=10000,
            workspace="Shared", organization_code="ORG_A", entity_code="A1")
        maintained = native.upsert_customer(customer_code="ORDINARY", name="Maintained ordinary customer", currency_code="EGP", credit_limit_minor=20000,
            workspace="Shared", organization_code="ORG_A", entity_code="A1", expected_version=customer["row_version"])
        assert maintained["credit_limit_minor"] == 20000
        for statement in (
            "UPDATE reconforge.legal_entities SET name='Maintained entity' WHERE tenant_id='finance_scope' AND id='entity_a1'",
            "UPDATE reconforge.finance_accounts SET name='Maintained account' WHERE tenant_id='finance_scope' AND account_code='A_CASH'",
            "UPDATE reconforge.finance_journals SET name='Maintained journal' WHERE tenant_id='finance_scope' AND journal_code='J_A'",
            "UPDATE reconforge.fiscal_periods SET name='Maintained period' WHERE tenant_id='finance_scope' AND id='period'",
        ):
            assert connection.execute(statement).rowcount == 1
    with db["boundary"].transaction("finance_scope") as connection:
        assert connection.execute("SELECT name FROM reconforge.ar_customers WHERE customer_code='ORDINARY'").fetchone()[0] == "Maintained ordinary customer"
