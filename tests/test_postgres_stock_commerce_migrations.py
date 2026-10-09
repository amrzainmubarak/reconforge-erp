"""Actual empty migration roundtrip and retained commercial-history refusal."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from reconforge.infrastructure.postgres_stock_commerce_schema import DOWNGRADE_SQL
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_stock_commerce import commercial_order
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database


def test_empty_real_migration_roundtrip_preserves_native_owners(receipt_database: tuple[str, str]) -> None:
    import psycopg
    admin_dsn, _app_dsn = receipt_database
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "RECONFORGE_POSTGRES_DSN": admin_dsn}
    with psycopg.connect(admin_dsn) as connection:
        before = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        native_count = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname='reconforge' AND tablename NOT LIKE 'stock_commerce_%'").fetchone()[0]
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0115_pg_financial_installments"], cwd=root, env=env, check=True, timeout=120)
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute("SELECT to_regclass('reconforge.stock_commerce_orders')").fetchone()[0] is None
        assert connection.execute("SELECT to_regclass('reconforge.stock_sales_orders')").fetchone()[0]
        assert connection.execute("SELECT to_regclass('reconforge.financial_installment_plans')").fetchone()[0]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, check=True, timeout=120)
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == before
        assert connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname='reconforge' AND tablename NOT LIKE 'stock_commerce_%'").fetchone()[0] == native_count


def test_populated_commercial_downgrade_refuses_source_history(receipt_database: tuple[str, str]) -> None:
    import psycopg
    runtime = create_stock_runtime(receipt_database)
    result = commercial_order(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="Commercial history exists"), psycopg.connect(receipt_database[0]) as connection:
        connection.execute(DOWNGRADE_SQL)
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT row_version FROM reconforge.stock_commerce_orders WHERE tenant_id=%s AND id=%s", (runtime.tenant, result["id"])).fetchone()["row_version"] == 3
