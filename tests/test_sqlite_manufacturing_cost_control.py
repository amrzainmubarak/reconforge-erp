from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from reconforge.application.manufacturing_cost_control import run_manufacturing_cost_control_files
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.domain.manufacturing_cost_control import ManufacturingControlRun
from reconforge.infrastructure.sqlite_manufacturing_cost_control import (
    ManufacturingCostControlPersistenceError,
    SQLiteManufacturingCostControlRepository,
)

ORDERS = Path("examples/manufacturing_cost_control/orders.json")
ISSUES = Path("examples/manufacturing_cost_control/issues.json")
COMPLETIONS = Path("examples/manufacturing_cost_control/completions.json")
SCRAP = Path("examples/manufacturing_cost_control/scrap.json")


def _run() -> ManufacturingControlRun:
    return run_manufacturing_cost_control_files(
        ORDERS,
        ISSUES,
        COMPLETIONS,
        SCRAP,
        currency="EUR",
        tolerance="0.01",
        max_scrap_quantity="2",
        unit="PCS",
    )


def _database(tmp_path: Path, *, target_version: int | None = None) -> sqlite3.Connection:
    path = tmp_path / "manufacturing.db"
    run_migrations(path, target_version=target_version)
    return connect(path, require_exists=True)


def test_manufacturing_persistence_is_idempotent_workspace_scoped_and_replay_verified(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    try:
        repository = SQLiteManufacturingCostControlRepository(connection)
        run = _run()
        first = repository.put(run, workspace="plant-a", actor_label="local-cli")
        replay = repository.put(run, workspace="plant-a", actor_label="local-cli")
        assert replay == first
        assert repository.get(decision_digest=run.decision_digest, workspace="plant-a") == first
        assert repository.list(workspace="plant-a") == (first,)
        assert repository.list(workspace="plant-b") == ()
        assert first["report"]["decision_digest"] == run.decision_digest
        assert first["report"]["status_counts"] == run.status_counts
    finally:
        connection.close()


def test_manufacturing_persistence_rejects_tampered_payload_after_outer_rehash(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    try:
        repository = SQLiteManufacturingCostControlRepository(connection)
        run = _run()
        saved = repository.put(run, workspace="plant-a")
        connection.execute("DROP TRIGGER manufacturing_cost_control_runs_no_update")
        payload = json.loads(
            str(
                connection.execute(
                    "SELECT payload_json FROM manufacturing_cost_control_runs WHERE id=?", (saved["id"],)
                ).fetchone()[0]
            )
        )
        payload["decisions"][0]["reason_codes"] = ["TAMPERED"]
        payload["artifact_digest"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "artifact_digest"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        connection.execute(
            "UPDATE manufacturing_cost_control_runs SET payload_json=?, artifact_digest=? WHERE id=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), payload["artifact_digest"], saved["id"]),
        )
        connection.commit()
        with pytest.raises(ManufacturingCostControlPersistenceError, match="replay verification"):
            repository.get(decision_digest=run.decision_digest, workspace="plant-a")
    finally:
        connection.close()


def test_manufacturing_repository_requires_migration_38(tmp_path: Path) -> None:
    connection = _database(tmp_path, target_version=37)
    try:
        with pytest.raises(ManufacturingCostControlPersistenceError, match="migration is required"):
            SQLiteManufacturingCostControlRepository(connection)
    finally:
        connection.close()


def test_manufacturing_persistence_survives_local_backup_restore(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    run_migrations(source)
    connection = connect(source, require_exists=True)
    try:
        saved = SQLiteManufacturingCostControlRepository(connection).put(_run(), workspace="plant-a")
    finally:
        connection.close()
    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    restored_connection = connect(restored, require_exists=True)
    try:
        replay = SQLiteManufacturingCostControlRepository(restored_connection).get(
            decision_digest=str(saved["decision_digest"]), workspace="plant-a"
        )
        assert replay == saved
    finally:
        restored_connection.close()


def test_manufacturing_persistence_boundary_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/infrastructure/sqlite_manufacturing_cost_control.py" in manifest
    assert "include tests/test_sqlite_manufacturing_cost_control.py" in manifest
