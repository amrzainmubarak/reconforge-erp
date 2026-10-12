"""Finance natural keys must resolve inside canonical PostgreSQL authority."""
from __future__ import annotations

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from queue import Queue
from time import monotonic, sleep
from typing import Any

import pytest

from reconforge.infrastructure.postgres import (
    PostgresRuntimePooledConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreError, PostgresFinanceCoreRepository
from reconforge.platform.common import PlatformError
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn
TABLES = ("finance_charts", "finance_accounts", "finance_dimensions", "finance_dimension_values", "finance_journals", "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions")


def _scope(connection: Any) -> tuple[Any, ...]:
    return tuple(connection.execute("SELECT current_setting('app.tenant_id',true),current_setting('app.organization_id',true),current_setting('app.workspace_id',true),current_setting('app.legal_entity_id',true),current_setting('app.entity_id',true)").fetchone())


def _policies(connection: Any) -> list[tuple[Any, ...]]:
    return list(connection.execute("SELECT tablename,policyname,permissive,cmd,qual,with_check FROM pg_policies WHERE schemaname='reconforge' AND tablename=ANY(%s) ORDER BY tablename,policyname", (list(TABLES),)))


def _entry(finance: Any, number: str, *, org: str = "A", entity: str = "A1", workspace: str = "Shared", period: str = "period") -> dict[str, Any]:
    return finance.create_entry(entry_number=number, organization_code=f"ORG_{org}", entity_code=entity, period_id=period, journal_code=f"J_{org}", posting_date="2026-07-28", description="Synthetic scoped entry", workspace=workspace, actor_label="maker", lines=[{"account_code": f"{org}_CASH", "debit": "100.00", "dimensions": {f"D_{org}": "V", "D_SHARED": "V"}}, {"account_code": f"{org}_CAPITAL", "credit": "100.00"}])


@pytest.fixture
def finance_database(isolated_postgres_migration_dsn: str, request: pytest.FixtureRequest):
    import psycopg
    from alembic.config import Config

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "0094_pg_finance_policy")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role))
        before_policies = _policies(admin)
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES('finance_scope','Synthetic')")
        admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES('finance_scope','shared','Shared'),('finance_scope','other','Other')")
        admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('finance_scope','EGP','Synthetic',2)")
        for org, workspace in (("a", "shared"), ("b", "shared"), ("legacy", "shared")):
            admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES('finance_scope',%s,%s,%s,'EGP',%s)", (f"org_{org}", f"ORG_{org.upper()}", org, workspace))
        # Application repositories resolve organization ownership through this
        # canonical bridge rather than the legacy convenience column above.
        # Keep ``org_legacy`` absent so the later upgrade assertion still
        # exercises an unprovable historical ownership record.
        admin.execute(
            """INSERT INTO reconforge.master_data_workspace_organizations
               (tenant_id,workspace_id,organization_id)
               VALUES ('finance_scope','shared','org_a'),('finance_scope','shared','org_b')"""
        )
        for entity, org in (("a1", "a"), ("a2", "a"), ("b1", "b"), ("legacy", "legacy")):
            admin.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES('finance_scope',%s,%s,%s,%s,'EGP')", (f"entity_{entity}", f"org_{org}", entity.upper(), entity))
        for period, workspace in (("period", "shared"), ("other_period", "other")):
            admin.execute("INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES('finance_scope',%s,%s,'2026-07-01','2026-07-31',2026,7,%s)", (period, period, workspace))
    factory = PostgresRuntimePooledConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False), max_size=2)
    boundary = PostgresTenantBoundary(factory)
    try:
        entries = {}
        with boundary.transaction("finance_scope") as connection:
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
            finance = PostgresFinanceCoreRepository(connection, "finance_scope")
            for org in ("A", "B", "LEGACY", "SHARED"):
                finance.upsert_dimension(dimension_code=f"D_{org}", name=org, workspace="Shared", organization_code="" if org == "SHARED" else f"ORG_{org}")
                finance.upsert_dimension_value(dimension_code=f"D_{org}", value_code="V", name=org, workspace="Shared")
                finance.upsert_chart(chart_code=org, name=org, workspace="Shared", organization_code="" if org == "SHARED" else f"ORG_{org}")
                for account, kind, balance in (("CASH", "Asset", "Debit"), ("CAPITAL", "Equity", "Credit")):
                    finance.upsert_account(account_code=f"{org}_{account}", name=account, workspace="Shared", chart_code=org, account_type=kind, normal_balance=balance)
                if org != "SHARED":
                    finance.upsert_journal(journal_code=f"J_{org}", name=org, organization_code=f"ORG_{org}", currency_code="EGP", workspace="Shared", chart_code=org)
            for entity, org in (("A1", "A"), ("A2", "A"), ("B1", "B"), ("LEGACY", "LEGACY")):
                entry = _entry(finance, f"ENTRY-{entity}", org=org, entity=entity)
                finance.validate_entry(entry["id"], reason="Synthetic independent review", actor_label="checker")
                entries[entity] = entry["id"]
            ids = {str(row[0]): str(row[1]) for row in connection.execute("SELECT account_code,id FROM reconforge.finance_accounts")}
            ids.update({f"chart_{row[0]}": str(row[1]) for row in connection.execute("SELECT chart_code,id FROM reconforge.finance_charts")})
            ids.update({f"dimension_{row[0]}": str(row[1]) for row in connection.execute("SELECT dimension_code,id FROM reconforge.finance_dimensions")})
            ids.update({f"value_{row[0]}": str(row[1]) for row in connection.execute("SELECT d.dimension_code,v.id FROM reconforge.finance_dimension_values v JOIN reconforge.finance_dimensions d ON d.id=v.dimension_id")})
        with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
            # Retain an explicit pre-0095 legacy row, without a guessed upgrade backfill.
            admin.execute("UPDATE reconforge.organizations SET application_workspace_id=NULL WHERE id='org_legacy'")
        # Historical downgrade tests stop at the revision under test. Applying
        # the later outbox fencing migration reserves legacy generations and
        # correctly makes that unrelated history irreversible.
        target_revision = getattr(request, "param", "head")
        command.upgrade(config, target_revision)
        with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
            # Upgrade introduces posting tables used by Finance integrity triggers.
            if admin.execute("SELECT to_regclass('reconforge.finance_posting_effects')").fetchone()[0] is not None:
                admin.execute(psycopg.sql.SQL(
                    "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.finance_posting_effects,reconforge.finance_posting_commands TO {}"
                ).format(psycopg.sql.Identifier(params["user"])))
            # Plain Finance writes run the additive source-closure trigger too.
            # It must read the forced-RLS source index without granting source mutations.
            for dependency in ("operational_finance_plans", "financial_opening_plans", "stock_sales_orders", "stock_sales_issue_claims", "procurement_partial_orders", "procurement_partial_receipts", "procurement_partial_invoices", "procurement_partial_commands"):
                qualified = "reconforge." + dependency
                if admin.execute("SELECT to_regclass(%s)", (qualified,)).fetchone()[0] is not None:
                    before = admin.execute("SELECT has_table_privilege(%s,%s,'INSERT'),has_table_privilege(%s,%s,'UPDATE'),has_table_privilege(%s,%s,'DELETE')", (params["user"],qualified,params["user"],qualified,params["user"],qualified)).fetchone()
                    admin.execute(psycopg.sql.SQL("GRANT SELECT ON {}.{} TO {}").format(psycopg.sql.Identifier("reconforge"),psycopg.sql.Identifier(dependency),psycopg.sql.Identifier(params["user"])))
                    after = admin.execute("SELECT has_table_privilege(%s,%s,'INSERT'),has_table_privilege(%s,%s,'UPDATE'),has_table_privilege(%s,%s,'DELETE')", (params["user"],qualified,params["user"],qualified,params["user"],qualified)).fetchone()
                    assert before == after
        yield {"factory": factory, "boundary": boundary, "entries": entries, "ids": ids, "admin": isolated_postgres_migration_dsn, "config": config, "before_policies": before_policies}
    finally:
        factory.close()


def test_live_finance_scope_hides_sibling_entries_and_denies_void(finance_database: Any) -> None:
    db = finance_database
    with db["boundary"].transaction("finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        before = _scope(connection)
        assert [r["entry_number"] for r in finance.list_entries(workspace="Shared")] == ["ENTRY-A1"]
        assert {r["chart_code"] for r in finance.list_charts(workspace="Shared")} == {"A", "SHARED"}
        assert {r[0] for r in connection.execute("SELECT DISTINCT entry_id FROM reconforge.finance_entry_lines")} == {db["entries"]["A1"]}
        assert {r[0] for r in connection.execute("SELECT dimension_code FROM reconforge.finance_dimensions")} == {"D_A", "D_SHARED"}
        assert connection.execute("SELECT count(*) FROM reconforge.finance_entry_line_dimensions").fetchone()[0] == 2
        for entity in ("A2", "B1", "LEGACY"):
            with pytest.raises(PlatformError):
                finance.get_entry(db["entries"][entity])
            with pytest.raises(PlatformError):
                finance.void_entry(db["entries"][entity], reason="Must not mutate sibling", actor_label="checker")
        assert finance.get_entry(db["entries"]["A1"])["total_debit"] == "100.00"
        assert _scope(connection) == before


def test_live_finance_scope_blocks_raw_relationship_laundering(finance_database: Any) -> None:
    import psycopg

    db = finance_database
    with db["boundary"].transaction("finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        before = _scope(connection)
        for statement, params in (
            ("UPDATE reconforge.finance_entry_lines SET account_id=%s WHERE tenant_id='finance_scope' AND entry_id=%s AND line_number=1", (db["ids"]["B_CASH"], db["entries"]["A1"])),
            ("UPDATE reconforge.finance_entries SET entity_code='A2' WHERE tenant_id='finance_scope' AND id=%s", (db["entries"]["A1"],)),
            ("UPDATE reconforge.finance_entries SET period_id='other_period' WHERE tenant_id='finance_scope' AND id=%s", (db["entries"]["A1"],)),
            ("UPDATE reconforge.finance_entry_line_dimensions SET dimension_value_id=%s WHERE tenant_id='finance_scope' AND dimension_id=%s", (db["ids"]["value_D_B"], db["ids"]["dimension_D_A"])),
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(statement, params)
            assert _scope(connection) == before
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        with pytest.raises(PlatformError, match="Fiscal-period"):
            _entry(finance, "WRONG-PERIOD", period="other_period")
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.finance_entries SELECT (jsonb_populate_record(NULL::reconforge.finance_entries,
                  to_jsonb(e)||jsonb_build_object('id','forged-period','entry_number','FORGED-PERIOD','period_id','other_period'))).*
                  FROM reconforge.finance_entries e WHERE id=%s""", (db["entries"]["A1"],),
            )


def test_live_finance_shared_references_are_readable_but_not_narrowly_mutable(finance_database: Any) -> None:
    boundary = finance_database["boundary"]
    for entity in (None, "entity_a1"):
        with boundary.transaction("finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id=entity) as connection:
            assert connection.execute("SELECT name FROM reconforge.finance_charts WHERE chart_code='SHARED'").fetchone() is not None
            assert connection.execute("UPDATE reconforge.finance_charts SET name='denied' WHERE chart_code='SHARED'").rowcount == 0
            assert connection.execute("DELETE FROM reconforge.finance_accounts WHERE account_code='SHARED_CASH'").rowcount == 0
            with pytest.raises(PostgresFinanceCoreError), connection.transaction():
                PostgresFinanceCoreRepository(connection, "finance_scope").upsert_chart(chart_code="NEW-SHARED", name="Denied", workspace="Shared")
            if entity:
                assert connection.execute("UPDATE reconforge.finance_charts SET name='denied' WHERE chart_code='A'").rowcount == 0
            else:
                assert connection.execute("UPDATE reconforge.finance_charts SET name='Allowed organization edit' WHERE chart_code='A'").rowcount == 1
    with boundary.transaction("finance_scope", workspace_id="shared") as connection:
        assert connection.execute("UPDATE reconforge.finance_charts SET name='Allowed workspace edit' WHERE chart_code='SHARED'").rowcount == 1


def test_live_finance_legacy_is_not_rebound_and_permitted_entity_workflow_succeeds(finance_database: Any) -> None:
    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        assert PostgresFinanceCoreRepository(connection, "finance_scope").get_entry(db["entries"]["LEGACY"])["entity_code"] == "LEGACY"
    with db["boundary"].transaction("finance_scope", organization_id="org_legacy", workspace_id="shared", legal_entity_id="entity_legacy") as connection:
        assert PostgresFinanceCoreRepository(connection, "finance_scope").list_entries(workspace="Shared") == []
    with db["boundary"].transaction("finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        draft = _entry(finance, "ALLOWED")
        assert finance.validate_entry(draft["id"], reason="Independent review", actor_label="checker")["status"] == "Validated"
        assert finance.trial_balance(period_id="period", organization_code="ORG_A", entity_code="A1", workspace="Shared")["totals"]["balanced"] is True
        assert finance.void_entry(draft["id"], reason="Synthetic correction", actor_label="checker")["status"] == "Voided"


@pytest.mark.parametrize("finance_database", ["0095_pg_finance_scope"], indirect=True)
def test_live_finance_scope_downgrade_restores_policies_and_replay(finance_database: Any) -> None:
    import psycopg

    from alembic import command

    db = finance_database
    command.downgrade(db["config"], "0094_pg_finance_policy")
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        assert _policies(admin) == db["before_policies"]
        assert admin.execute("SELECT count(*) FROM reconforge.finance_entries").fetchone()[0] == 4
    command.upgrade(db["config"], "head")
    with db["boundary"].transaction("finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        assert [tuple(row) for row in connection.execute("SELECT entry_number FROM reconforge.finance_entries")] == [("ENTRY-A1",)]


def test_live_current_head_refuses_legacy_outbox_evidence_loss(finance_database: Any) -> None:
    import psycopg

    from alembic import command

    db = finance_database
    with psycopg.connect(db["admin"]) as admin:
        revision = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        before = admin.execute(
            "SELECT event_id,lease_generation,lease_generation_floor FROM reconforge.outbox_events ORDER BY event_id"
        ).fetchall()
        assert before and all(row[1:] == (2, 2) for row in before)
    with pytest.raises(Exception, match="outbox fencing downgrade refused: non-default generations are retained"):
        command.downgrade(db["config"], "0094_pg_finance_policy")
    with psycopg.connect(db["admin"]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
        assert admin.execute(
            "SELECT event_id,lease_generation,lease_generation_floor FROM reconforge.outbox_events ORDER BY event_id"
        ).fetchall() == before
        assert admin.execute("SELECT count(*) FROM reconforge.finance_entries").fetchone()[0] == 4


def test_live_finance_identity_cannot_be_relabelled_or_deleted(finance_database: Any) -> None:
    import psycopg

    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        for statement in (
            "UPDATE reconforge.organizations SET organization_code='REBOUND' WHERE id='org_a'",
            "UPDATE reconforge.organizations SET application_workspace_id='other' WHERE id='org_a'",
            "UPDATE reconforge.legal_entities SET organization_id='org_b' WHERE id='entity_a1'",
            "UPDATE reconforge.legal_entities SET entity_code='REBOUND' WHERE id='entity_a1'",
            "UPDATE reconforge.fiscal_periods SET application_workspace_id='other' WHERE id='period'",
            "UPDATE reconforge.finance_charts SET organization_code='ORG_B' WHERE chart_code='A'",
            "UPDATE reconforge.finance_entries SET status='Draft' WHERE entry_number='ENTRY-A1'",
            "DELETE FROM reconforge.organizations WHERE id='org_a'",
            "DELETE FROM reconforge.legal_entities WHERE id='entity_a1'",
            "DELETE FROM reconforge.fiscal_periods WHERE id='period'",
            "UPDATE reconforge.finance_entry_lines SET entry_id=(SELECT id FROM reconforge.finance_entries WHERE entry_number='ENTRY-A2') WHERE entry_id=(SELECT id FROM reconforge.finance_entries WHERE entry_number='ENTRY-A1')",
        ):
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(statement)
        with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
            connection.execute("UPDATE reconforge.finance_accounts SET parent_account_id=(SELECT id FROM reconforge.finance_accounts WHERE account_code='B_CASH') WHERE account_code='A_CASH'")
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        draft = _entry(finance, "REPLACE")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("UPDATE reconforge.finance_entries SET entity_code='A2' WHERE id=%s", (draft["id"],))
        replacement = _entry(finance, "REPLACE", entity="A2")
        assert replacement["id"] == draft["id"]
        assert replacement["entity_code"] == "A2"
        assert len(replacement["lines"]) == 2
        # Every shared trigger branch must permit non-identity metadata edits.
        for table, identifier in (
            ("organizations", "org_a"), ("legal_entities", "entity_a1"), ("fiscal_periods", "period"),
            ("finance_charts", db["ids"]["chart_A"]), ("finance_accounts", db["ids"]["A_CASH"]),
            ("finance_dimensions", db["ids"]["dimension_D_A"]), ("finance_dimension_values", db["ids"]["value_D_A"]),
        ):
            statement = psycopg.sql.SQL("UPDATE reconforge.{} SET name=name WHERE id=%s").format(psycopg.sql.Identifier(table))
            assert connection.execute(statement, (identifier,)).rowcount == 1
        assert connection.execute("UPDATE reconforge.finance_journals SET name=name WHERE journal_code='J_A'").rowcount == 1


def test_live_finance_org_only_scope_cannot_read_shared_references_in_another_workspace(finance_database: Any) -> None:
    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        finance.upsert_chart(chart_code="OTHER-SHARED", name="Other shared", workspace="Other")
        finance.upsert_dimension(dimension_code="OTHER-SHARED", name="Other shared", workspace="Other")
        with pytest.raises(PlatformError):
            finance.upsert_chart(chart_code="FORGED-ORG", name="Wrong workspace", workspace="Other", organization_code="ORG_A")
    for entity in (None, "entity_a1"):
        with db["boundary"].transaction("finance_scope", organization_id="org_a", legal_entity_id=entity) as connection:
            finance = PostgresFinanceCoreRepository(connection, "finance_scope")
            assert finance.list_charts(workspace="Other") == []
            assert finance.list_dimensions(workspace="Other") == []
            assert {r["chart_code"] for r in finance.list_charts(workspace="Shared")} == {"A", "SHARED"}


def test_live_current_finance_installer_enforces_scope_without_historical_root_policies(finance_database: Any) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_finance_core import install_postgres_finance_core_schema

    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        PostgresFinanceCoreRepository(connection, "finance_scope").upsert_chart(chart_code="OTHER-SHARED", name="Other", workspace="Other")
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        # Recreate the base policies produced by direct schema installers, without
        # relying on 0041/0044 having strengthened canonical parents beforehand.
        for table in (*TABLES, "domain_workspaces", "organizations", "legal_entities", "fiscal_periods"):
            policies = list(admin.execute("SELECT policyname FROM pg_policies WHERE schemaname='reconforge' AND tablename=%s", (table,)))
            for policy in policies:
                admin.execute(psycopg.sql.SQL("DROP POLICY {} ON reconforge.{}").format(psycopg.sql.Identifier(policy[0]), psycopg.sql.Identifier(table)))
            admin.execute(psycopg.sql.SQL("CREATE POLICY tenant_scope ON reconforge.{} USING (tenant_id=current_setting('app.tenant_id',true)) WITH CHECK (tenant_id=current_setting('app.tenant_id',true))").format(psycopg.sql.Identifier(table)))
        install_postgres_finance_core_schema(admin)
    for workspace in (None, "shared"):
        with db["boundary"].transaction("finance_scope", organization_id="org_a", workspace_id=workspace, legal_entity_id="entity_a1") as connection:
            finance = PostgresFinanceCoreRepository(connection, "finance_scope")
            assert [r["entry_number"] for r in finance.list_entries(workspace="Shared")] == ["ENTRY-A1"]
            assert finance.list_charts(workspace="Other") == []
    with db["boundary"].transaction("finance_scope", workspace_id="shared") as connection:
        assert PostgresFinanceCoreRepository(connection, "finance_scope").list_charts(workspace="Other") == []


def test_live_finance_workspace_name_ambiguity_requires_explicit_id(finance_database: Any) -> None:
    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        connection.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES('finance_scope','duplicate_one','Duplicate'),('finance_scope','duplicate_two','Duplicate')")
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        with pytest.raises(PostgresFinanceCoreError, match="ambiguous"):
            finance.list_entries(workspace="Duplicate")
        assert finance.list_entries(workspace="duplicate_one") == []
        assert finance.list_entries(workspace="duplicate_two") == []


def _wait_for_lock(admin_dsn: str, backend_id: int) -> None:
    import psycopg

    deadline = monotonic() + 10
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        while monotonic() < deadline:
            row = admin.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (backend_id,)).fetchone()
            if row and row[0] == "Lock":
                return
            sleep(0.01)
    pytest.fail("Synthetic concurrent statement did not wait on its canonical parent lock")


@pytest.mark.parametrize("writer_first", [True, False], ids=["writer-before-delete", "delete-before-writer"])
def test_live_finance_parent_delete_serializes_with_new_reference(finance_database: Any, writer_first: bool) -> None:
    import psycopg

    db = finance_database
    boundary = db["boundary"]
    with boundary.transaction("finance_scope") as connection:
        connection.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,application_workspace_id) VALUES('finance_scope','org_race','ORG_RACE','Synthetic race','shared')")
    backend_ids: Queue[int] = Queue()

    def second_actor() -> str:
        try:
            with boundary.transaction("finance_scope") as second:
                backend_ids.put(second.execute("SELECT pg_backend_pid()").fetchone()[0])
                if writer_first:
                    second.execute("DELETE FROM reconforge.organizations WHERE id='org_race'")
                else:
                    PostgresFinanceCoreRepository(second, "finance_scope").upsert_chart(chart_code="RACE", name="Race", organization_code="ORG_RACE", workspace="Shared")
            return "committed"
        except (psycopg.Error, PostgresFinanceCoreError):
            return "denied"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with boundary.transaction("finance_scope") as first:
            if writer_first:
                PostgresFinanceCoreRepository(first, "finance_scope").upsert_chart(chart_code="RACE", name="Race", organization_code="ORG_RACE", workspace="Shared")
            else:
                first.execute("DELETE FROM reconforge.organizations WHERE id='org_race'")
            outcome = executor.submit(second_actor)
            _wait_for_lock(db["admin"], backend_ids.get(timeout=10))
        assert outcome.result(timeout=10) == "denied"
    with boundary.transaction("finance_scope") as connection:
        assert connection.execute("SELECT count(*) FROM reconforge.organizations WHERE id='org_race'").fetchone()[0] == int(writer_first)
        assert connection.execute("SELECT count(*) FROM reconforge.finance_charts WHERE chart_code='RACE'").fetchone()[0] == int(writer_first)


@pytest.mark.parametrize("child_first", [True, False], ids=["line-before-reparent", "reparent-before-line"])
def test_live_finance_draft_scope_replacement_serializes_with_new_line(finance_database: Any, child_first: bool) -> None:
    import psycopg

    db = finance_database
    boundary = db["boundary"]
    with boundary.transaction("finance_scope") as connection:
        draft = _entry(PostgresFinanceCoreRepository(connection, "finance_scope"), "DRAFT-RACE")
        connection.execute("DELETE FROM reconforge.finance_entry_lines WHERE entry_id=%s", (draft["id"],))
    backend_ids: Queue[int] = Queue()

    def insert_line(connection: Any) -> None:
        connection.execute("INSERT INTO reconforge.finance_entry_lines(tenant_id,id,entry_id,line_number,account_id,debit_minor,credit_minor,currency_code) VALUES('finance_scope','race-line',%s,1,%s,10000,0,'EGP')", (draft["id"], db["ids"]["A_CASH"]))

    def second_actor() -> str:
        try:
            scope = {} if child_first else {"organization_id": "org_a", "workspace_id": "shared", "legal_entity_id": "entity_a1"}
            with boundary.transaction("finance_scope", **scope) as second:
                backend_ids.put(second.execute("SELECT pg_backend_pid()").fetchone()[0])
                if child_first:
                    second.execute("UPDATE reconforge.finance_entries SET entity_code='A2' WHERE id=%s", (draft["id"],))
                else:
                    insert_line(second)
            return "committed"
        except psycopg.Error:
            return "denied"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with boundary.transaction("finance_scope") as first:
            if child_first:
                insert_line(first)
            else:
                first.execute("UPDATE reconforge.finance_entries SET entity_code='A2' WHERE id=%s", (draft["id"],))
            outcome = executor.submit(second_actor)
            _wait_for_lock(db["admin"], backend_ids.get(timeout=10))
        assert outcome.result(timeout=10) == "denied"
    with boundary.transaction("finance_scope") as connection:
        assert connection.execute("SELECT entity_code FROM reconforge.finance_entries WHERE id=%s", (draft["id"],)).fetchone()[0] == ("A1" if child_first else "A2")
        assert connection.execute("SELECT count(*) FROM reconforge.finance_entry_lines WHERE entry_id=%s", (draft["id"],)).fetchone()[0] == int(child_first)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_live_finance_parent_deletion_rejects_a_stale_transaction_snapshot(finance_database: Any, isolation: str) -> None:
    import psycopg

    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        connection.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,application_workspace_id) VALUES('finance_scope','org_empty','ORG_EMPTY','Unreferenced','shared')")
    with (
        closing(db["factory"].connect()) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="fresh read committed"),
        connection.transaction(),
    ):
        connection.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        set_local_tenant_scope(connection, "finance_scope")
        connection.execute("DELETE FROM reconforge.organizations WHERE id='org_empty'")
    with db["boundary"].transaction("finance_scope") as connection:
        assert connection.execute("SELECT id FROM reconforge.organizations WHERE id='org_empty'").fetchone() is not None


def test_finance_scope_migration_is_frozen_and_matches_installer() -> None:
    from reconforge.infrastructure.postgres_finance_scope import POSTGRES_FINANCE_SCOPE_SCHEMA_SQL

    path = Path("alembic/versions/0095_postgres_finance_scope.py")
    spec = importlib.util.spec_from_file_location("finance_scope_revision", path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.UPGRADE_SQL == POSTGRES_FINANCE_SCOPE_SCHEMA_SQL
    assert revision.down_revision == "0094_pg_finance_policy"
    assert "load_postgres_schema_sql" not in path.read_text(encoding="utf-8")
