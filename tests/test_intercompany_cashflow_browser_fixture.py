"""Actual browser read fixture qualification; no wire execution is inferred."""

import psycopg
import pytest

from tests.intercompany_cashflow_browser import (
    INTERCOMPANY_CASHFLOW_RESTORE_TAMPER,
    intercompany_cashflow_restore_tamper_actor,
    seed_intercompany_cashflow_browser,
    verify_intercompany_cashflow_browser,
)
from tests.test_postgres_intercompany_cashflow import write_original
from tests.test_postgres_intercompany_fx import intercompany_fx_database, receipt_database

__all__ = ["intercompany_fx_database", "receipt_database"]
pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def test_actual_reviewed_browser_fixture_read_and_valid_native_tamper_leave_originals_unchanged(intercompany_fx_database):
    base = seed_intercompany_cashflow_browser(*intercompany_fx_database)
    before = verify_intercompany_cashflow_browser(base)
    assert before["browser_financial_writes"] is False and before["native_effect_count"] == 7
    with intercompany_cashflow_restore_tamper_actor(base) as (connection, _, _actor):
        for statement in INTERCOMPANY_CASHFLOW_RESTORE_TAMPER:
            with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
                connection.execute(statement, (base.tenant,))
            assert refused.value.diag.constraint_name == "intercompany_fx_owner"
    assert verify_intercompany_cashflow_browser(base) == before
    write_original(before["original_evidence"])
