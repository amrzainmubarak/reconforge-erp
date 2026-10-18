"""Populated 0122 upgrades retain rows, ownership, privileges and source closure."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from reconforge.domain.finance_posting import digest_payload
from tests.test_postgres_fixed_assets import acquire, finish, seed_asset_masters
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime, receipt_database
from tests.test_postgres_landed_cost import CHECKER, POSTER, create_multiline_runtime, create_order, phase, prepare

__all__ = ["receipt_database"]
FUNCTIONS = ["asset_reverse_close", "landed_cost_reverse_close"]


def _catalog(connection: Any) -> str:
    return digest_payload({
        "tables": connection.execute("""SELECT relname,relowner,relacl,relrowsecurity,relforcerowsecurity
            FROM pg_class WHERE relnamespace='reconforge'::regnamespace AND relkind IN ('r','p') ORDER BY relname""").fetchall(),
        "policies": connection.execute("SELECT * FROM pg_policies WHERE schemaname='reconforge' ORDER BY tablename,policyname").fetchall(),
        "functions": connection.execute("""SELECT oid,proname,proowner,proacl,prosecdef,proconfig
            FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname=ANY(%s) ORDER BY proname""", (FUNCTIONS,)).fetchall(),
        "triggers": connection.execute("""SELECT t.oid,c.relname,t.tgname,t.tgfoid,t.tgdeferrable,t.tginitdeferred,t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace='reconforge'::regnamespace
            AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""").fetchall(),
    })


def _rows(connection: Any) -> str:
    from psycopg import sql

    tables = connection.execute("""SELECT tablename FROM pg_tables WHERE schemaname='reconforge' ORDER BY tablename""").fetchall()
    return digest_payload({name: connection.execute(sql.SQL("SELECT to_jsonb(r) FROM reconforge.{} r ORDER BY to_jsonb(r)::text")
        .format(sql.Identifier(name))).fetchall() for (name,) in tables})


def test_populated_0122_forward_dispatch_refresh_and_compatible_rollback(receipt_database: tuple[str, str]) -> None:
    import psycopg

    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "RECONFORGE_POSTGRES_DSN": receipt_database[0]}

    def migrate(operation: str, revision: str) -> None:
        subprocess.run([sys.executable, "-m", "alembic", operation, revision], cwd=root,
                       env=environment, check=True, timeout=180)

    migrate("downgrade", "0122_pg_fixed_assets")
    landed_runtime = create_multiline_runtime(receipt_database)
    landed = phase(landed_runtime, phase(landed_runtime, prepare(landed_runtime, create_order(landed_runtime)),
                                      "review", CHECKER), "post", POSTER)
    asset_runtime = seed_asset_masters(create_receipt_runtime(receipt_database))
    asset = finish(asset_runtime, acquire(asset_runtime))
    assert landed["phase"] == asset["phase"] == 2
    with psycopg.connect(receipt_database[0]) as admin:
        before_rows, before_catalog = _rows(admin), _catalog(admin)
        for name in FUNCTIONS:
            definition = admin.execute("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname=%s", (name,)).fetchone()[0]
            assert definition.count("DECLARE ") == 1
            # Mark the existing invoker body without changing business behavior.
            # A true forward migration must replace it; installer early-return
            # would incorrectly leave the pre-upgrade body in place.
            admin.execute(definition.replace("DECLARE ", "-- pre0123-refresh-marker\nDECLARE ", 1))
        assert _catalog(admin) == before_catalog
    # This compatibility case verifies the exact 0122 -> 0123 refresh.
    # Later storage-owning revisions have separate populated upgrade gates.
    migrate("upgrade", "0123_pg_native_event_dispatch")
    with psycopg.connect(receipt_database[0]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0123_pg_native_event_dispatch"
        assert _rows(admin) == before_rows and _catalog(admin) == before_catalog
        bodies = admin.execute("SELECT prosrc FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname=ANY(%s)", (FUNCTIONS,)).fetchall()
        assert len(bodies) == 2 and all("pre0123-refresh-marker" not in body for (body,) in bodies)
    # Storage/code rollback retains the compatible fix and all protected rows.
    migrate("downgrade", "0122_pg_fixed_assets")
    with psycopg.connect(receipt_database[0]) as admin:
        assert _rows(admin) == before_rows and _catalog(admin) == before_catalog
        with pytest.raises(psycopg.errors.RaiseException, match="refuses to discard retained financial evidence"), admin.transaction():
            from reconforge.infrastructure.postgres_fixed_assets_schema import DOWNGRADE_SQL

            admin.execute(DOWNGRADE_SQL)
        with pytest.raises(psycopg.errors.RaiseException, match="Retained landed costs prohibit downgrade"), admin.transaction():
            from reconforge.infrastructure.postgres_landed_cost_schema import DOWNGRADE_SQL

            admin.execute(DOWNGRADE_SQL)
        assert _rows(admin) == before_rows
    migrate("upgrade", "head")
