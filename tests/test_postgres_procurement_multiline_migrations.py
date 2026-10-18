"""Additive multiline schema recovery preserves retained native history."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_postgres_procurement_multiline import (
    MAKER,
    create_multiline_runtime,
    create_order,
    enterprise_digest,
    pytestmark,
    receipt_database,
)

__all__ = ["pytestmark", "receipt_database"]


def test_empty_multiline_schema_roundtrip_and_populated_history_refusal(receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_procurement_partial_multiline_schema import DOWNGRADE_SQL
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "RECONFORGE_POSTGRES_DSN": receipt_database[0]}
    # Later owners reference these tables. Test the real ordered rollback rather
    # than dropping a middle revision's tables underneath retained dependencies.
    with psycopg.connect(receipt_database[0]) as admin:
        before = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
        grants = admin.execute("""SELECT table_name,privilege_type FROM information_schema.role_table_grants
            WHERE table_schema='reconforge' AND grantee=%s ORDER BY table_name,privilege_type""", (app_user,)).fetchall()
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0116_pg_stock_commerce"],
                   cwd=root, env=environment, check=True, timeout=120)
    with psycopg.connect(receipt_database[0]) as admin:
        assert admin.execute("SELECT to_regclass('reconforge.procurement_partial_order_lines')").fetchone()[0] is None
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=root, env=environment, check=True, timeout=120)
    with psycopg.connect(receipt_database[0]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == before
        # Recreated tables lose ACLs. Restore exactly the pre-rollback fixture
        # grants, without expanding privilege or bypassing their RLS policies.
        for table, privilege in grants:
            assert privilege in {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN"}
            admin.execute(sql.SQL("GRANT {} ON reconforge.{} TO {}").format(
                sql.SQL(privilege), sql.Identifier(table), sql.Identifier(app_user)))
        assert admin.execute("""SELECT table_name,privilege_type FROM information_schema.role_table_grants
            WHERE table_schema='reconforge' AND grantee=%s ORDER BY table_name,privilege_type""", (app_user,)).fetchall() == grants
        rows = admin.execute("""SELECT relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE relnamespace='reconforge'::regnamespace AND relname IN ('procurement_partial_order_lines','procurement_partial_invoice_lines')""").fetchall()
        assert len(rows) == 2 and all(tuple(row) == (True, True) for row in rows)
    runtime = create_multiline_runtime(receipt_database)
    view = create_order(runtime, "HISTORY-PRESERVED")
    with runtime.actor(MAKER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    with psycopg.connect(receipt_database[0]) as admin, pytest.raises(
        psycopg.errors.RaiseException, match="Retained multiline procurements prohibit downgrade"
    ), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
    with runtime.actor(MAKER) as (connection, _, actor):
        from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
        assert enterprise_digest(connection, runtime.tenant) == before
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
