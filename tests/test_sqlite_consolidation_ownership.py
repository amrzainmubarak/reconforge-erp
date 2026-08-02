from __future__ import annotations

import sqlite3
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.migrations import MIGRATIONS
from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest
from reconforge.infrastructure.sqlite_consolidation_ownership import (
    SQLiteConsolidationOwnershipRepository,
)
from reconforge.platform.common import PlatformError


def _digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _interest(interest_id: str, *, effective_from: str, effective_to: str = "") -> ConsolidationOwnershipInterest:
    return ConsolidationOwnershipInterest(
        interest_id=interest_id,
        parent_entity_code="PARENT",
        subsidiary_entity_code="SUB",
        direct_ownership_percentage=Decimal("0.80"),
        effective_from=effective_from,
        effective_to=effective_to,
        version="1.0.0",
        source_digest=_digest(interest_id),
        prepared_by="ownership-preparer",
        approved_by="ownership-reviewer",
        approved_at="2026-08-01T00:00:00Z",
    )


def _database(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    path = tmp_path / "ownership.db"
    run_migrations(path)
    return path, connect(path, require_exists=True)


def test_migration_26_persists_effective_dated_ownership_and_replays_by_date(tmp_path: Path) -> None:
    assert MIGRATIONS[-1].version == 26
    assert MIGRATIONS[-1].name == "consolidation_ownership_masters"
    path, connection = _database(tmp_path)
    try:
        repository = SQLiteConsolidationOwnershipRepository(connection)
        first = repository.save_interest(
            _interest("OWN-2026-H1", effective_from="2026-01-01", effective_to="2026-06-30"),
            group_code="GLOBAL-GROUP",
            actor_label="ownership-preparer",
        )
        second = repository.save_interest(
            _interest("OWN-2026-H2", effective_from="2026-07-01"),
            group_code="GLOBAL-GROUP",
            actor_label="ownership-preparer",
        )
        assert first["interest_id"] == "OWN-2026-H1"
        assert [item.interest_id for item in repository.resolve_effective(
            group_code="GLOBAL-GROUP", reporting_date="2026-03-31", actor_label="reader"
        )] == ["OWN-2026-H1"]
        assert [item.interest_id for item in repository.resolve_effective(
            group_code="GLOBAL-GROUP", reporting_date="2026-08-01", actor_label="reader"
        )] == ["OWN-2026-H2"]
        assert second["workspace_id"] == first["workspace_id"]
        with pytest.raises(PlatformError, match="overlap"):
            repository.save_interest(
                _interest("OWN-OVERLAP", effective_from="2026-06-15", effective_to="2026-07-15"),
                group_code="GLOBAL-GROUP",
                actor_label="ownership-preparer",
            )
    finally:
        connection.close()
    assert path.exists()


def test_ownership_revisions_are_immutable_and_workspace_isolated(tmp_path: Path) -> None:
    _path, connection = _database(tmp_path)
    try:
        repository = SQLiteConsolidationOwnershipRepository(connection)
        repository.save_interest(
            _interest("OWN-SAME-ID", effective_from="2026-01-01"),
            group_code="GLOBAL-GROUP",
            workspace="alpha",
            actor_label="ownership-preparer",
        )
        repository.save_interest(
            _interest("OWN-SAME-ID", effective_from="2026-01-01"),
            group_code="GLOBAL-GROUP",
            workspace="beta",
            actor_label="ownership-preparer",
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE consolidation_ownership_interests SET approved_by='tamper'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute("DELETE FROM consolidation_ownership_interests")
        assert repository.get_interest(
            "OWN-SAME-ID", group_code="GLOBAL-GROUP", workspace="alpha", actor_label="reader"
        )["workspace_id"] != repository.get_interest(
            "OWN-SAME-ID", group_code="GLOBAL-GROUP", workspace="beta", actor_label="reader"
        )["workspace_id"]
    finally:
        connection.close()


def test_backup_restore_replays_ownership_master(tmp_path: Path) -> None:
    source_path, connection = _database(tmp_path / "source")
    try:
        repository = SQLiteConsolidationOwnershipRepository(connection)
        repository.save_interest(
            _interest("OWN-RESTORE", effective_from="2026-01-01"),
            group_code="GLOBAL-GROUP",
            actor_label="ownership-preparer",
        )
    finally:
        connection.close()
    backup = create_backup(source_path, tmp_path / "backup")
    restored_path = tmp_path / "restored.db"
    restore_backup(restored_path, backup.backup_path)
    restored_connection = connect(restored_path, require_exists=True)
    try:
        restored = SQLiteConsolidationOwnershipRepository(restored_connection)
        result = restored.resolve_effective(
            group_code="GLOBAL-GROUP", reporting_date="2026-08-01", actor_label="reader"
        )
        assert [item.interest_id for item in result] == ["OWN-RESTORE"]
    finally:
        restored_connection.close()
