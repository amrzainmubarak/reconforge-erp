"""Populated SQLite49 rebuilds are atomic, including destructive-DDL faults."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_inventory_receipt_posting_schema import (
    SQLITE_INVENTORY_RECEIPT_MIGRATION_SQL,
    atomic_receipt_upgrade,
)
from tests.test_finance_core import _create_entry
from tests.test_sqlite_finance_posting import _actor, _post, _posting_actor, _reviewed


@pytest.fixture(scope="module")
def populated49(tmp_path_factory):
    path = tmp_path_factory.mktemp("receipt_upgrade_original") / "populated49.db"
    run_migrations(path, target_version=49)
    connection = connect(path, require_exists=True)
    finance, period, repository, preview, _maker, checker = _reviewed(connection)
    with _actor(connection, "checker"):
        effect = _post(repository, preview, checker)
    with _actor(connection, "maker"):
        _create_entry(finance, period, number="UNPOSTED-49", actor="maker")
    connection.close()
    return path, effect


def _copy(source: Path, target: Path):
    original = connect(source, require_exists=True)
    copied = connect(target, create_parent=True)
    original.backup(copied)
    original.close()
    return copied


def _upgrade(connection, checkpoint=None):
    atomic_receipt_upgrade(
        connection,
        schema_sql=SQLITE_INVENTORY_RECEIPT_MIGRATION_SQL,
        version=50,
        name="reviewed_inventory_receipt_posting",
        applied_at="2026-10-03T00:00:00Z",
        checkpoint=checkpoint,
    )


@pytest.mark.parametrize("stage", ["copied", "dropped", "renamed", "guards", "verified", "marked"])
def test_populated_upgrade_fault_restores_schema_rows_version_and_flags(
    tmp_path: Path, populated49, stage: str
) -> None:
    connection = _copy(populated49[0], tmp_path / f"fault-{stage}.db")
    try:
        before = tuple(connection.iterdump())

        def fault(observed):
            if observed == stage:
                raise RuntimeError("synthetic migration failure after " + stage)

        with pytest.raises(RuntimeError, match="synthetic migration"):
            _upgrade(connection, fault)
        assert not connection.in_transaction
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 49
        assert tuple(connection.iterdump()) == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='inventory_receipt_plans'").fetchone() is None
    finally:
        connection.close()


def test_populated_upgrade_preserves_historical_posting_and_replay(tmp_path: Path, populated49) -> None:
    from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository, verify_posting_storage

    connection = _copy(populated49[0], tmp_path / "success.db")
    try:
        before_effect = tuple(connection.execute("SELECT * FROM finance_posting_effects").fetchone())
        before_commands = [tuple(row) for row in connection.execute("SELECT * FROM finance_posting_commands")]
        _upgrade(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 50
        assert tuple(connection.execute("SELECT * FROM finance_posting_effects").fetchone()) == before_effect
        assert [tuple(row) for row in connection.execute("SELECT * FROM finance_posting_commands")] == before_commands
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        with _actor(connection, "checker") as principal:
            repository = SQLiteFinancePostingRepository(connection)
            assert repository.get_effect(populated49[1]["id"], actor=_posting_actor(principal)) == populated49[1]
        verify_posting_storage(connection)
        before_reinstall = tuple(connection.iterdump())
        assert run_migrations(tmp_path / "success.db", target_version=50).current_version == 50
        assert tuple(connection.iterdump()) == before_reinstall
    finally:
        connection.close()


@pytest.mark.parametrize("label", ["IRP1-LEGACY", "irp1-legacy", "IrP1-Legacy"])
def test_namespace_collision_refuses_before_any_schema_mutation(tmp_path: Path, populated49, label: str) -> None:
    connection = _copy(populated49[0], tmp_path / "collision.db")
    try:
        connection.execute("UPDATE ledger_entries SET entry_number=? WHERE status='Draft'", (label,))
        connection.commit()
        before = tuple(connection.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="namespace collision"):
            _upgrade(connection)
        assert tuple(connection.iterdump()) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 49
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_unknown_dependent_schema_refuses_and_preserves_it(tmp_path: Path, populated49) -> None:
    connection = _copy(populated49[0], tmp_path / "custom.db")
    try:
        connection.execute("CREATE INDEX custom_effect_index ON finance_posting_effects(reason)")
        connection.commit()
        before = tuple(connection.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="Unexpected Finance"):
            _upgrade(connection)
        assert tuple(connection.iterdump()) == before
    finally:
        connection.close()
