"""Repository schema setup must preserve caller-owned quality transaction state."""

import sqlite3

import pytest

from reconforge.infrastructure.sqlite_manufacturing_quality import SqliteManufacturingQualityRepository


def test_quality_constructor_cannot_commit_the_callers_pending_changes() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE pending_financial_effect(amount_minor INTEGER)")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO pending_financial_effect VALUES(10001)")
        SqliteManufacturingQualityRepository(connection)
        assert connection.in_transaction
        connection.rollback()
        assert connection.execute("SELECT * FROM pending_financial_effect").fetchall() == []
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'quality_%'",
        ).fetchall() == []


@pytest.mark.parametrize("caller_transaction", [False, True])
def test_failed_quality_schema_setup_leaves_no_partial_schema(caller_transaction: bool) -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE pending_financial_effect(amount_minor INTEGER)")
        if caller_transaction:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO pending_financial_effect VALUES(10001)")

        def deny_last_table(action: int, name: str, *_: object) -> int:
            if action == sqlite3.SQLITE_CREATE_TABLE and name == "quality_rework_orders":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_last_table)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            SqliteManufacturingQualityRepository(connection)
        connection.set_authorizer(None)
        assert connection.in_transaction is caller_transaction
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'quality_%'",
        ).fetchall() == []
        if caller_transaction:
            assert connection.execute("SELECT * FROM pending_financial_effect").fetchall() == [(10001,)]
            connection.rollback()
            assert connection.execute("SELECT * FROM pending_financial_effect").fetchall() == []
