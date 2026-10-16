"""Real148/149 migration custody, existing function identity and safe downgrade."""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    install_postgres_customer_partial_return_transfer_hooks,
)
from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import (
    install_postgres_inventory_receipt_posting_schema,
)
from reconforge.infrastructure.postgres_monetary_installation import verify_monetary_installation_if_present
from reconforge.infrastructure.postgres_monetary_stock_schema import DOWNGRADE_PREFLIGHT_SQL, DROP_STORAGE_SQL
from reconforge.infrastructure.postgres_monetary_stock_schema import TABLES as MONETARY_TABLES
from reconforge.platform.common import PlatformError
from tests.gfo_browser_restore import database_snapshot
from tests.test_postgres_customer_partial_return_rounding import (
    create_remainder_runtime,
    phase_v2,
    prepare_v2,
)
from tests.test_postgres_customer_partial_returns import SETTLEMENT_TABLES
from tests.test_postgres_customer_returns import configure_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_monetary_customer_partial_returns import _stock
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database
OLD = "0148_pg_partial_return_rounding"
NEW = "0149_pg_monetary_partial_returns"
FUNCTIONS = (
    "stock_sales_admit", "stock_sales_protect", "stock_sales_close", "stock_sales_public",
    "fx_close", "fx_command_actor", "fx_valuation_equation", "inventory_cost_layer_guard",
    "guard_inventory_receipt_layer_history_complete", "guard_inventory_receipt_link", "customer_partial_return_zero_layer_guard",
    "customer_partial_return_zero_stock_active", "customer_partial_return_zero_stock_plan", "it1_cost_snapshot", "it1_cost_originals", "it1_stock_origins",
    "inventory_quantity_free_fifo",
)


def _revision(dsn, direction, revision):
    subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn}, check=True, timeout=180)


def _profiles(connection):
    rows = connection.execute("""SELECT p.oid,p.proname,p.proowner,p.proacl,p.prolang,p.prorettype,p.prokind,p.prosecdef,
        p.proisstrict,p.proretset,p.provolatile,p.proparallel,p.proconfig,p.proargnames,p.pronargdefaults,p.prosrc
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' AND p.proname=ANY(%s)
        ORDER BY p.proname,p.oid""", (list(FUNCTIONS),)).fetchall()
    assert len(FUNCTIONS) == len(set(FUNCTIONS)) == len(rows) == 17
    return {row["proname"]: dict(row) for row in rows}


@pytest.fixture
def populated148_database() -> Iterator[tuple[str, str]]:
    """A separate function-owned DB: the module fixture can retain149 Drafts."""
    name = "reconforge_monetary_compat_" + uuid4().hex[:16]
    admin_url = urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])
    admin = urlunsplit(admin_url._replace(path="/" + name))
    app = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_DSN"], dbname=name)
    control_dsn = psycopg.conninfo.make_conninfo(admin, dbname="postgres", connect_timeout=5)
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        _revision(admin, "upgrade", OLD)
        from reconforge.infrastructure.postgres_receipt_admission import install_postgres_receipt_admission

        with psycopg.connect(admin) as connection:
            install_postgres_inventory_receipt_posting_schema(connection)
            install_postgres_receipt_admission(connection)
            role = psycopg.conninfo.conninfo_to_dict(app)["user"]
            assert type(role) is str and role
            # These privileges belong only to this owned synthetic fixture.
            for statement in ("GRANT USAGE ON SCHEMA reconforge TO {}",
                              "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}",
                              "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}"):
                connection.execute(sql.SQL(statement).format(sql.Identifier(role)))
        yield admin, app
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone() is None


def _old_financial_rows(runtime):
    """All79 original table memberships, with hashes instead of private rows."""
    assert len(SETTLEMENT_TABLES) == len(set(SETTLEMENT_TABLES)) == 79
    result = {}
    with runtime.actor("maker") as (connection, _, _actor):
        for name in SETTLEMENT_TABLES:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r "
                "WHERE tenant_id=%s ORDER BY to_jsonb(r)::text COLLATE \"C\"").format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
            raw = json.dumps([row["original"] for row in rows], separators=(",", ":"), ensure_ascii=False).encode()
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256(raw).hexdigest()}
    return result


def _ack_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def test_actual_retained_posted148_v2_source_and_ack_survive149_upgrade(populated148_database):
    admin_dsn, app_dsn = populated148_database
    runtime, source = create_remainder_runtime(populated148_database)
    command = "retained148-v2-native-prepare"
    prepared = prepare_v2(runtime, source, 1, 0, command)
    reviewed = phase_v2(runtime, prepared, "review", "checker")
    posted = phase_v2(runtime, reviewed, "post", "poster")
    assert posted["phase"] == 2 and posted["allocation_policy"] == "remaining-original-v1"
    assert (posted["credit_minor"], posted["cogs_restored_minor"]) == (1000, 334)
    acknowledgements = tuple(_ack_digest(value) for value in (prepared, reviewed, posted))
    financial_before = _old_financial_rows(runtime)
    assert financial_before["customer_partial_return_history"]["rows"] == 1
    assert financial_before["customer_partial_return_allocation_witnesses"]["rows"] == 1
    before = database_snapshot(admin_dsn)
    assert before["head"] == OLD and all(name not in before["tables"] for name in MONETARY_TABLES)
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        original_profiles = _profiles(admin)
        assert verify_monetary_installation_if_present(admin) is False
    _revision(admin_dsn, "upgrade", NEW)
    upgraded = database_snapshot(admin_dsn)
    assert upgraded["head"] == NEW and set(upgraded["tables"]) == set(before["tables"]) | set(MONETARY_TABLES)
    assert all(upgraded["tables"][name] == rows for name, rows in before["tables"].items())
    role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
    assert type(role) is str and role
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        assert verify_monetary_installation_if_present(admin) is True
        current_profiles = _profiles(admin)
        assert {name: {key: value for key, value in row.items() if key != "prosrc"} for name, row in original_profiles.items()} == {
            name: {key: value for key, value in row.items() if key != "prosrc"} for name, row in current_profiles.items()}
        for name in MONETARY_TABLES:
            assert admin.execute(sql.SQL("SELECT count(*) n FROM reconforge.{}").format(sql.Identifier(name))).fetchone()["n"] == 0
            assert admin.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE') allowed",
                                 (role, "reconforge." + name)).fetchone()["allowed"] is False
            # Upgrade grants no business privileges. A recreated/new table is
            # admitted explicitly only for this test's ordinary runtime role.
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}")
                          .format(sql.Identifier(name), sql.Identifier(role)))
    with runtime.actor("maker") as (connection, _, _actor):
        flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication "
                                   "FROM pg_roles WHERE rolname=current_user").fetchone()
        assert all(flags[name] is False for name in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb", "rolreplication"))
    assert financial_before == _old_financial_rows(runtime)
    replayed = (prepare_v2(runtime, source, 1, 0, command), phase_v2(runtime, prepared, "review", "checker"),
                phase_v2(runtime, reviewed, "post", "poster"))
    assert tuple(_ack_digest(value) for value in replayed) == acknowledgements
    assert financial_before == _old_financial_rows(runtime)
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        for name in MONETARY_TABLES:
            assert admin.execute(sql.SQL("SELECT count(*) n FROM reconforge.{}").format(sql.Identifier(name))).fetchone()["n"] == 0


def test_actual_empty_roundtrip_preserves_original_oids_acl_and_exact_execution_attributes(receipt_database):
    admin_dsn, app_dsn = receipt_database
    _revision(admin_dsn, "downgrade", OLD)
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        before = _profiles(admin)
        assert verify_monetary_installation_if_present(admin) is False
    _revision(admin_dsn, "upgrade", NEW)
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        assert verify_monetary_installation_if_present(admin) is True
        upgraded = _profiles(admin)
        assert {name: {key: value for key, value in row.items() if key != "prosrc"} for name, row in before.items()} == {
            name: {key: value for key, value in row.items() if key != "prosrc"} for name, row in upgraded.items()}
        install_postgres_inventory_receipt_posting_schema(admin)
        install_postgres_customer_partial_return_transfer_hooks(admin)
        assert _profiles(admin) == upgraded
    # Reinstallation uses both normal tuple and Mapping psycopg cursors. It may
    # verify149, but may never overwrite the retained monetary dispatch bodies.
    with psycopg.connect(admin_dsn) as admin:
        install_postgres_inventory_receipt_posting_schema(admin)
        install_postgres_customer_partial_return_transfer_hooks(admin)
        assert verify_monetary_installation_if_present(admin) is True
    _revision(admin_dsn, "downgrade", OLD)
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        assert _profiles(admin) == before
        assert verify_monetary_installation_if_present(admin) is False
    _revision(admin_dsn, "upgrade", NEW)
    # The roundtrip recreated these tables after the module fixture's grants.
    # Restore only that owned fixture role's explicit admission for later tests.
    role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
    assert type(role) is str and role
    with psycopg.connect(admin_dsn) as admin:
        for name in MONETARY_TABLES:
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}")
                          .format(sql.Identifier(name), sql.Identifier(role)))


def test_actual_new_native_function_and_force_rls_drift_refuse_without_repair(receipt_database):
    admin_dsn, _ = receipt_database
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        before = _profiles(admin)
        # ROLLBACK is deliberate fault containment in this owned synthetic DB.
        with pytest.raises(PlatformError), admin.transaction():
            admin.execute("ALTER TABLE reconforge.customer_partial_return_monetary_history NO FORCE ROW LEVEL SECURITY")
            verify_monetary_installation_if_present(admin)
        assert verify_monetary_installation_if_present(admin) is True
        with pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
            admin.execute("ALTER FUNCTION reconforge.monetary_stock_zero_active(TEXT,TEXT) STABLE")
            verify_monetary_installation_if_present(admin)
        assert _profiles(admin) == before
        assert verify_monetary_installation_if_present(admin) is True
        with pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
            admin.execute("ALTER POLICY scope ON reconforge.customer_partial_return_monetary_history USING(TRUE) WITH CHECK(TRUE)")
            verify_monetary_installation_if_present(admin)
        assert verify_monetary_installation_if_present(admin) is True
        with pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
            admin.execute("ALTER TABLE reconforge.operational_fx_plans DROP CONSTRAINT monetary_fx_journal_presence")
            admin.execute("ALTER TABLE reconforge.operational_fx_plans ADD CONSTRAINT monetary_fx_journal_presence CHECK(TRUE)")
            verify_monetary_installation_if_present(admin)
        assert verify_monetary_installation_if_present(admin) is True


def test_actual_unrecognized_monetary_draft_blocks_destructive_downgrade(receipt_database):
    runtime = create_stock_runtime(receipt_database)
    configure_runtime(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        draft = _stock(connection, runtime).create(StockOrder("RETAINED-MONETARY-DRAFT", "CUSTOMER", "PO", "ITEM", "MAIN", "STOCK", "1",
            100, "USD", "2026-10-16", "Retained source protocol requires compatible schema"), command_id="retained:create", actor=actor)
        assert draft["status"] == "Draft"
    with psycopg.connect(runtime.admin_dsn, row_factory=dict_row) as admin:
        before = _profiles(admin)
    with pytest.raises(subprocess.CalledProcessError):
        _revision(runtime.admin_dsn, "downgrade", OLD)
    with psycopg.connect(runtime.admin_dsn, row_factory=dict_row) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"] == NEW
        assert _profiles(admin) == before and verify_monetary_installation_if_present(admin) is True
        row = admin.execute(sql.SQL("SELECT status,source->>'schema_version' schema_version FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s"),
                            (runtime.tenant, draft["id"])).fetchone()
        assert dict(row) == {"status": "Draft", "schema_version": "stock-sales-monetary-order-v2"}


def test_actual_force_rls_ddl_owner_cannot_misread_hidden_draft_as_safe_downgrade(populated148_database):
    """Ownership permits DROP; hidden retained evidence must still stop preflight."""
    admin_dsn, app_dsn = populated148_database
    _revision(admin_dsn, "upgrade", NEW)
    app_role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
    with psycopg.connect(admin_dsn) as admin:
        # Only this separate synthetic fixture admits the newly created tables.
        for name in MONETARY_TABLES:
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}")
                          .format(sql.Identifier(name), sql.Identifier(app_role)))
    runtime = create_stock_runtime(populated148_database)
    configure_runtime(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        draft = _stock(connection, runtime).create(StockOrder("RLS-HIDDEN-MONETARY-DRAFT", "CUSTOMER", "PO", "ITEM", "MAIN", "STOCK", "1",
            100, "USD", "2026-10-16", "Genuine retained Draft under forced RLS"), command_id="rls-downgrade:create", actor=actor)
        assert draft["status"] == "Draft"
    before = database_snapshot(admin_dsn)
    assert before["head"] == NEW
    role = "monetary_ddl_owner_" + uuid4().hex[:12]
    guard_tables = (*MONETARY_TABLES, "stock_sales_orders", "stock_sales_commands", "operational_fx_sources", "operational_fx_plans", "finance_entries",
                    "organizations", "legal_entities")

    class RollBackOwnedDrop(Exception):
        """Force rollback of the positive, permission-complete DDL probe."""

    all_profiles_sql = ("SELECT p.oid,to_jsonb(p) native_profile FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' ORDER BY p.oid")
    with psycopg.connect(admin_dsn, row_factory=dict_row) as admin:
        profiles_before = _profiles(admin)
        all_profiles_before = admin.execute(all_profiles_sql).fetchall()
        assert admin.execute("SELECT count(*) n FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
                             (runtime.tenant, draft["id"])).fetchone()["n"] == 1
        assert admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None
        try:
            # Role creation, fixture grants and ownership all roll back below;
            # no persistent cluster role or business-role privilege is added.
            admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
                          .format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT USAGE,CREATE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
            for name in MONETARY_TABLES:
                admin.execute(sql.SQL("ALTER TABLE reconforge.{} OWNER TO {}")
                              .format(sql.Identifier(name), sql.Identifier(role)))
            for name in guard_tables:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}")
                              .format(sql.Identifier(name), sql.Identifier(role)))
            admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            flags = admin.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
                                  "FROM pg_roles WHERE rolname=current_user").fetchone()
            assert all(value is False for value in flags.values())
            ownership = admin.execute("SELECT c.relname,c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) owned,"
                "c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='reconforge' AND c.relname=ANY(%s) ORDER BY c.relname", (list(MONETARY_TABLES),)).fetchall()
            assert len(ownership) == len(MONETARY_TABLES) == 7
            assert all(row["owned"] and row["relrowsecurity"] and row["relforcerowsecurity"] for row in ownership)
            schema_rights = admin.execute("SELECT has_schema_privilege(current_user,'reconforge','USAGE') usage,"
                                          "has_schema_privilege(current_user,'reconforge','CREATE') create_schema").fetchone()
            assert all(value is True for value in schema_rights.values())
            for name in guard_tables:
                assert admin.execute("SELECT has_table_privilege(current_user,%s,'SELECT') allowed",
                                     ("reconforge." + name,)).fetchone()["allowed"] is True
            assert admin.execute("SHOW row_security").fetchone()["row_security"] == "on"
            stock_rls = admin.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                                      "WHERE oid='reconforge.stock_sales_orders'::regclass").fetchone()
            assert all(value is True for value in stock_rls.values())
            assert admin.execute("SELECT count(*) n FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
                                 (runtime.tenant, draft["id"])).fetchone()["n"] == 0
            # This is an actual successful DROP by the very same ordinary role,
            # contained by a savepoint. Missing DDL rights cannot explain refusal.
            with pytest.raises(RollBackOwnedDrop), admin.transaction():
                admin.execute("DROP TABLE reconforge.customer_partial_return_monetary_commands")
                assert admin.execute("SELECT to_regclass('reconforge.customer_partial_return_monetary_commands') absent").fetchone()["absent"] is None
                raise RollBackOwnedDrop
            assert admin.execute("SELECT to_regclass('reconforge.customer_partial_return_monetary_commands') present").fetchone()["present"] is not None
            destructive_reached = False
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused, admin.transaction():
                admin.execute(DOWNGRADE_PREFLIGHT_SQL)
                destructive_reached = True
                admin.execute(DROP_STORAGE_SQL)
            assert refused.value.sqlstate == "42501" and destructive_reached is False
            assert refused.value.diag.message_primary == 'query would be affected by row-level security policy for table "stock_sales_orders"'
            # The failing savepoint also restores transaction-local row_security.
            assert admin.execute("SHOW row_security").fetchone()["row_security"] == "on"
            admin.execute("RESET ROLE")
            assert _profiles(admin) == profiles_before
            assert admin.execute(all_profiles_sql).fetchall() == all_profiles_before
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"] == NEW
            assert admin.execute("SELECT count(*) n FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
                                 (runtime.tenant, draft["id"])).fetchone()["n"] == 1
        finally:
            admin.rollback()
        assert admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None
        assert _profiles(admin) == profiles_before and verify_monetary_installation_if_present(admin) is True
        assert admin.execute(all_profiles_sql).fetchall() == all_profiles_before
    assert database_snapshot(admin_dsn) == before
