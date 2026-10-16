"""Real148/149 migration custody, existing function identity and safe downgrade."""

import os
import subprocess
import sys
from pathlib import Path

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
from reconforge.platform.common import PlatformError
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
)


def _revision(dsn, direction, revision):
    subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn}, check=True, timeout=180)


def _profiles(connection):
    rows = connection.execute("""SELECT p.oid,p.proname,p.proowner,p.proacl,p.prolang,p.prorettype,p.prokind,p.prosecdef,
        p.proisstrict,p.proretset,p.provolatile,p.proparallel,p.proconfig,p.proargnames,p.pronargdefaults,p.prosrc
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' AND p.proname=ANY(%s)
        ORDER BY p.proname,p.oid""", (list(FUNCTIONS),)).fetchall()
    assert len(rows) == 16
    return {row["proname"]: dict(row) for row in rows}


def test_actual_empty_roundtrip_preserves_original_oids_acl_and_exact_execution_attributes(receipt_database):
    admin_dsn, _ = receipt_database
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
