"""Independent populated CRM migration and authority integrity regressions."""

import sqlite3
from pathlib import Path

import pytest

from reconforge.db.connection import DatabaseError
from reconforge.db.migrations import run_migrations
from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.infrastructure.sqlite_crm_contracts import SqliteCRMContractsRepository


def _legacy_database(path: Path, *, ownership: str = "unique") -> None:
    run_migrations(path, target_version=58)
    with sqlite3.connect(path) as connection:
        if ownership != "orphan":
            _insert_quotation(connection, "workspace-a")
        if ownership == "collision":
            _insert_quotation(connection, "workspace-b")
        connection.execute(
            "INSERT INTO crm_quotation_lines VALUES(?,?,?,?,?,?,?)",
            ("legacy-quote", 1, "item", "Synthetic legacy evidence", 3, 10001, 37),
        )


def _insert_quotation(connection: sqlite3.Connection, workspace: str) -> None:
    connection.execute(
        "INSERT INTO crm_quotations VALUES(?,?,?,?,?,?,?,?,?,?)",
        (workspace, "legacy-quote", "opportunity", "customer", "USD", "2026-12-31",
         "unverified-legacy-author", "draft", None, None),
    )


def _snapshot(connection: sqlite3.Connection) -> tuple[object, ...]:
    return (
        connection.execute("SELECT sql FROM sqlite_master WHERE name='crm_quotation_lines'").fetchone(),
        connection.execute("SELECT * FROM crm_quotation_lines ORDER BY quote_id,line_number").fetchall(),
        connection.execute("SELECT * FROM crm_quotations ORDER BY workspace_id,quote_id").fetchall(),
    )


def test_populated_58_upgrade_preserves_lines_without_inferred_authority(tmp_path: Path) -> None:
    path = tmp_path / "crm.sqlite"
    _legacy_database(path)
    status = run_migrations(path, target_version=59)
    assert status.applied_versions == [59]
    with sqlite3.connect(path) as connection:
        repository = SqliteCRMContractsRepository(connection)
        assert connection.execute("SELECT * FROM crm_quotation_lines").fetchall() == [
            ("workspace-a", "legacy-quote", 1, "item", "Synthetic legacy evidence", 3, 10001, 37),
        ]
        assert repository.quotation_author_id("workspace-a", "legacy-quote") is None
        assert connection.execute("SELECT * FROM crm_quotation_authorities").fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert run_migrations(path, target_version=59).applied_versions == []


@pytest.mark.parametrize("ownership", ["collision", "orphan"])
def test_ambiguous_legacy_upgrade_refuses_without_data_loss(tmp_path: Path, ownership: str) -> None:
    path = tmp_path / "crm.sqlite"
    _legacy_database(path, ownership=ownership)
    with sqlite3.connect(path) as connection:
        before = _snapshot(connection)
    with pytest.raises(DatabaseError) as failure:
        run_migrations(path, target_version=59)
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    assert "Ambiguous legacy CRM" in str(failure.value.__cause__)
    with sqlite3.connect(path) as connection:
        assert _snapshot(connection) == before
        assert connection.execute("PRAGMA user_version").fetchone() == (58,)
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (58,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='crm_quotation_lines_legacy59'",
        ).fetchone() is None


@pytest.mark.parametrize("operation", ["UPDATE crm_quotation_authorities SET user_id='forged'",
                                       "DELETE FROM crm_quotation_authorities"])
def test_authority_update_and_delete_are_refused(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "crm.sqlite"
    _legacy_database(path)
    run_migrations(path, target_version=59)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO crm_quotation_authorities VALUES(?,?,?,'canonical-user-v1')",
            ("workspace-a", "legacy-quote", "canonical-user"),
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(operation)
        assert connection.execute("SELECT * FROM crm_quotation_authorities").fetchall() == [
            ("workspace-a", "legacy-quote", "canonical-user", "canonical-user-v1"),
        ]


def test_migration_record_failure_rolls_back_schema_and_data(tmp_path: Path) -> None:
    path = tmp_path / "crm.sqlite"
    _legacy_database(path)
    with sqlite3.connect(path) as connection:
        before = _snapshot(connection)
        connection.executescript("""
            CREATE TRIGGER reject_migration_59 BEFORE INSERT ON schema_migrations
            WHEN NEW.version=59 BEGIN SELECT RAISE(ABORT,'synthetic marker refusal'); END;
        """)
    with pytest.raises(DatabaseError) as failure:
        run_migrations(path, target_version=59)
    assert "synthetic marker refusal" in str(failure.value.__cause__)
    with sqlite3.connect(path) as connection:
        assert _snapshot(connection) == before
        assert connection.execute("PRAGMA user_version").fetchone() == (58,)
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (58,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='crm_quotation_authorities'",
        ).fetchone() is None


@pytest.mark.parametrize("failed_table", ["crm_quotation_authorities", "crm_quotation_lines"])
def test_quotation_creation_refusal_is_atomic(tmp_path: Path, failed_table: str) -> None:
    path = tmp_path / "crm.sqlite"
    run_migrations(path, target_version=59)
    with sqlite3.connect(path) as connection:
        repository = SqliteCRMContractsRepository(connection)
        # Only the closed, parametrized table names above enter this synthetic trigger.
        connection.executescript(
            "CREATE TRIGGER reject_creation BEFORE INSERT ON " + failed_table
            + " BEGIN SELECT RAISE(ABORT,'synthetic creation refusal'); END;",
        )
        quote = CustomerQuotation(
            quote_id="new-quote", opportunity_id="opportunity", workspace_id="workspace-a",
            customer_id="customer", currency="USD", valid_until="2026-12-31",
            submitter_user_id="canonical-user", status="draft",
            lines=(QuotationLineItem(1, "item", "Synthetic line", 1, 10001),),
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic creation refusal"):
            repository.save_quotation(quote, author_user_id="canonical-user")
        assert connection.execute("SELECT * FROM crm_quotations").fetchall() == []
        assert connection.execute("SELECT * FROM crm_quotation_authorities").fetchall() == []
        assert connection.execute("SELECT * FROM crm_quotation_lines").fetchall() == []


@pytest.mark.parametrize("ownership", ["unique", "collision"])
def test_repository_constructor_preserves_caller_transaction(tmp_path: Path, ownership: str) -> None:
    path = tmp_path / "crm.sqlite"
    _legacy_database(path, ownership=ownership)
    with sqlite3.connect(path) as connection:
        before = _snapshot(connection)
        connection.execute("CREATE TABLE caller_pending(value TEXT)")
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO caller_pending VALUES('uncommitted')")
        if ownership == "collision":
            with pytest.raises(sqlite3.IntegrityError, match="Ambiguous legacy CRM"):
                SqliteCRMContractsRepository(connection)
        else:
            SqliteCRMContractsRepository(connection)
            assert "workspace_id" in {
                row[1] for row in connection.execute("PRAGMA table_info(crm_quotation_lines)")
            }
        assert connection.in_transaction
        assert connection.execute("SELECT * FROM caller_pending").fetchall() == [("uncommitted",)]
        connection.rollback()
        assert connection.execute("SELECT * FROM caller_pending").fetchall() == []
        assert _snapshot(connection) == before
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='crm_quotation_authorities'",
        ).fetchone() is None
