"""Additive multiline schema recovery preserves retained native history."""
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

    from reconforge.infrastructure.postgres_procurement_partial_multiline_schema import DOWNGRADE_SQL, UPGRADE_SQL
    with psycopg.connect(receipt_database[0]) as admin:
        admin.execute(DOWNGRADE_SQL)
        assert admin.execute("SELECT to_regclass('reconforge.procurement_partial_order_lines')").fetchone()[0] is None
        admin.execute(UPGRADE_SQL)
        app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
        for name in ("procurement_partial_order_lines", "procurement_partial_invoice_lines"):
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(name), sql.Identifier(app_user)))
        rows = admin.execute("""SELECT relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE relnamespace='reconforge'::regnamespace AND relname IN ('procurement_partial_order_lines','procurement_partial_invoice_lines')""").fetchall()
        assert len(rows) == 2 and all(tuple(row) == (True, True) for row in rows)
    runtime = create_multiline_runtime(receipt_database)
    view = create_order(runtime, "HISTORY-PRESERVED")
    with runtime.actor(MAKER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    with psycopg.connect(receipt_database[0]) as admin:
        with pytest.raises(psycopg.errors.RaiseException, match="Retained multiline procurements prohibit downgrade"), admin.transaction():
            admin.execute(DOWNGRADE_SQL)
    with runtime.actor(MAKER) as (connection, _, actor):
        from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
        assert enterprise_digest(connection, runtime.tenant) == before
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
