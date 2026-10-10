"""Separate owned database validates empty valuation rollback over posted FX1."""

from reconforge.infrastructure.postgres_operational_fx_revaluation_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_fx_revaluation import revalue_fx
from tests.test_postgres_operational_fx_tax import finish_fx, fx_runtime, prepare_fx, pytestmark, receipt_database

__all__ = ["fx_runtime", "pytestmark", "receipt_database"]


def test_empty_revaluation_rollback_preserves_original_posted_source_and_reupgrade(fx_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = fx_runtime
    original = finish_fx(runtime, prepare_fx(runtime))
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresOperationalFxTaxRepository(connection, runtime.tenant).plan_evidence(original["id"], actor=actor)["native_effect"]["id"] == original["posting_effect_id"]
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(UPGRADE_SQL)
    finish_fx(runtime, revalue_fx(runtime, original["source_id"]))
