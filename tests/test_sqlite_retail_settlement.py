from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.domain.retail_settlement import (
    RetailPosBatch,
    RetailProcessorSettlement,
    RetailSettlementRun,
    run_retail_settlement,
)
from reconforge.infrastructure.sqlite_retail_settlement import (
    RetailSettlementPersistenceError,
    SQLiteRetailSettlementRepository,
)
from reconforge.utils.money import Money


def _money(value: str) -> Money:
    return Money.from_exact(value, "USD")


def _run() -> RetailSettlementRun:
    pos = RetailPosBatch(
        "POS-1",
        "STORE-1",
        "2026-08-04",
        "USD",
        _money("100.00"),
        _money("5.00"),
        _money("20.00"),
        _money("0.00"),
        _money("0.00"),
        _money("0.00"),
        10,
        "pos-source-1",
    )
    settlement = RetailProcessorSettlement(
        "SET-1",
        "POS-1",
        "STORE-1",
        "2026-08-05",
        "USD",
        _money("100.00"),
        _money("5.00"),
        _money("2.00"),
        _money("0.00"),
        _money("93.00"),
        "provider-1",
    )
    return run_retail_settlement((pos,), (settlement,), tolerance=_money("0.01"))


def _database(tmp_path: Path, *, target_version: int | None = None) -> sqlite3.Connection:
    path = tmp_path / "retail.db"
    run_migrations(path, target_version=target_version)
    return connect(path, require_exists=True)


def test_retail_persistence_is_idempotent_workspace_scoped_and_replay_verified(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    try:
        repository = SQLiteRetailSettlementRepository(connection)
        run = _run()
        first = repository.put(run, workspace="shop-a", actor_label="local-cli")
        replay = repository.put(run, workspace="shop-a", actor_label="local-cli")
        assert replay == first
        assert repository.get(decision_digest=run.decision_digest, workspace="shop-a") == first
        assert repository.list(workspace="shop-a") == (first,)
        assert repository.list(workspace="shop-b") == ()
        assert first["report"]["decision_digest"] == run.decision_digest
    finally:
        connection.close()


def test_retail_persistence_rejects_tampered_payload_on_read(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    try:
        repository = SQLiteRetailSettlementRepository(connection)
        run = _run()
        saved = repository.put(run, workspace="shop-a")
        connection.execute("DROP TRIGGER retail_settlement_runs_no_update")
        payload = json.loads(
            str(
                connection.execute(
                    "SELECT payload_json FROM retail_settlement_runs WHERE id=?", (saved["id"],)
                ).fetchone()[0]
            )
        )
        payload["decisions"][0]["status"] = "exception"
        payload["artifact_digest"] = ""
        payload["artifact_digest"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "artifact_digest"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        connection.execute(
            "UPDATE retail_settlement_runs SET payload_json=?, artifact_digest=? WHERE id=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), payload["artifact_digest"], saved["id"]),
        )
        connection.commit()
        with pytest.raises(RetailSettlementPersistenceError, match="replay verification"):
            repository.get(decision_digest=run.decision_digest, workspace="shop-a")
    finally:
        connection.close()


def test_retail_repository_requires_migration_35(tmp_path: Path) -> None:
    connection = _database(tmp_path, target_version=34)
    try:
        with pytest.raises(RetailSettlementPersistenceError, match="migration is required"):
            SQLiteRetailSettlementRepository(connection)
    finally:
        connection.close()


def test_retail_persistence_boundary_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/adr/0448-retail-settlement-persistence.md" in manifest
    assert "include reconforge/infrastructure/sqlite_retail_settlement.py" in manifest
    assert "include tests/test_sqlite_retail_settlement.py" in manifest


def test_retail_persistence_survives_local_backup_restore(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    run_migrations(source)
    connection = connect(source, require_exists=True)
    try:
        saved = SQLiteRetailSettlementRepository(connection).put(_run(), workspace="shop-a")
    finally:
        connection.close()
    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    restored_connection = connect(restored, require_exists=True)
    try:
        replay = SQLiteRetailSettlementRepository(restored_connection).get(
            decision_digest=str(saved["decision_digest"]), workspace="shop-a"
        )
        assert replay == saved
    finally:
        restored_connection.close()
