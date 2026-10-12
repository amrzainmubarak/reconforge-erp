"""Additive schema roundtrip without adopting or deleting native financial history."""

import pytest

from reconforge.infrastructure.postgres_financial_reporting_snapshot_schema import DOWNGRADE_SQL, UPGRADE_SQL
from tests.test_postgres_inventory_receipt_posting import receipt_database

__all__ = ["receipt_database"]


def test_empty_snapshot_schema_roundtrip_repeated_install_keeps_force_rls_and_native_history(receipt_database: tuple[str, str]) -> None:
    import psycopg
    with psycopg.connect(receipt_database[0]) as connection:
        connection.execute(UPGRADE_SQL)
        connection.execute(UPGRADE_SQL)
        assert connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname IN ('financial_report_captures','financial_report_members','financial_report_snapshots') AND c.relrowsecurity AND c.relforcerowsecurity").fetchone()[0] == 3
        original = connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0]
        connection.execute(DOWNGRADE_SQL)
        assert connection.execute("SELECT to_regclass('reconforge.financial_report_captures')").fetchone()[0] is None
        connection.execute(UPGRADE_SQL)
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == original
        with pytest.raises(psycopg.errors.CheckViolation, match="current human"), connection.transaction():
            connection.execute("""INSERT INTO reconforge.financial_report_captures(tenant_id,id,workspace_id,organization_id,legal_entity_id,map_id,period_id,as_of_date,actor_id,command_id,request_digest,request_json,source_snapshot,created_at)
            VALUES('absent','FRS1-forged','work','org','entity','absent','absent','2026-10-31','absent','forged',repeat('a',64),'{}','forged','2026-10-31T00:00:00Z')""")
