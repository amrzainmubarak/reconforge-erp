"""Actual native fixture/callback and valid tamper qualification, separate from TLS."""

import psycopg
import pytest

from tests.intercompany_group_diagnostic_browser import (
    INTERCOMPANY_GROUP_DIAGNOSTIC_RESTORE_TAMPER,
    intercompany_group_diagnostic_restore_tamper_actor,
    seed_intercompany_group_diagnostic_browser,
    verify_intercompany_group_diagnostic_browser,
)
from tests.test_postgres_intercompany_fx import intercompany_fx_database, receipt_database
from tests.test_postgres_intercompany_group_diagnostic import write_original

__all__ = ["intercompany_fx_database", "receipt_database"]
pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def test_actual_two_source_browser_fixture_stable_callback_and_three_valid_tamper_refusals(intercompany_fx_database):
    base = seed_intercompany_group_diagnostic_browser(*intercompany_fx_database)
    before = verify_intercompany_group_diagnostic_browser(base)
    assert before["source_count"] == 2 and before["native_effect_count"] == 14 and before["browser_financial_writes"] is False
    with intercompany_group_diagnostic_restore_tamper_actor(base) as (connection, _, _actor):
        for statement in INTERCOMPANY_GROUP_DIAGNOSTIC_RESTORE_TAMPER:
            with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
                connection.execute(statement, (base.tenant,))
            assert refused.value.diag.constraint_name == "intercompany_fx_owner"
    assert verify_intercompany_group_diagnostic_browser(base) == before
    write_original(before["original_evidence"])
