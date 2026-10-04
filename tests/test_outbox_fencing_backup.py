"""SQLite backup and restore preserve fenced outbox delivery evidence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import reconforge.db.backup as backup_module
import reconforge.db.migrations as migration_module
from reconforge.application.outbox import OutboxError
from reconforge.db import connect
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, checksum_file
from reconforge.infrastructure.outbox_fencing_schema import SQLITE_OUTBOX_FENCING_RESTORE_TRIGGER_NAMES
from reconforge.infrastructure.sqlite_outbox import SQLiteOutboxRepository
from reconforge.platform.common import append_outbox_event


def _set_migrations(monkeypatch: pytest.MonkeyPatch, migrations: list[migration_module.Migration]) -> None:
    monkeypatch.setattr(migration_module, "MIGRATIONS", migrations)
    monkeypatch.setattr(backup_module, "MIGRATIONS", migrations)


def _seed_fenced_database(tmp_path: Path) -> Path:
    db_path = tmp_path / "fenced-source.db"
    migration_module.run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_outbox_event(
            connection,
            event_id="published-event",
            event_type="synthetic.published",
            aggregate_type="synthetic",
            aggregate_id="published",
            payload={"synthetic": True},
        )
        connection.commit()
        repository = SQLiteOutboxRepository(connection)
        claim = repository.claim_pending(worker_id="publisher")[0]
        repository.mark_published(event_id=claim.id, worker_id="publisher", lease_generation=claim.lease_generation)
        append_outbox_event(
            connection,
            event_id="pending-event",
            event_type="synthetic.pending",
            aggregate_type="synthetic",
            aggregate_id="pending",
            payload={"synthetic": True},
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _rewrite_backup(result: Any, payload: dict[str, Any]) -> None:
    result.backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["backup.json"] = {
        "sha256": checksum_file(result.backup_path),
        "bytes": result.backup_path.stat().st_size,
    }
    result.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _trigger_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
    }


def test_v53_backup_restore_round_trip_retains_fenced_outbox_and_reinstalls_guards(tmp_path: Path) -> None:
    source_db = _seed_fenced_database(tmp_path)
    backup = create_backup(source_db, tmp_path / "v53-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    tables = payload["tables"]
    assert backup.schema_version >= 53
    assert {"lease_generation", "lease_generation_floor"} <= set(tables["outbox_events"][0])
    assert tables["outbox_delivery_evidence"] == [
        {
            "evidence_id": 1,
            "event_id": "published-event",
            "lease_generation": 1,
            "action": "claimed",
            "worker_id": "publisher",
            "occurred_at": tables["outbox_delivery_evidence"][0]["occurred_at"],
            "attempts": 0,
        },
        {
            "evidence_id": 2,
            "event_id": "published-event",
            "lease_generation": 1,
            "action": "published",
            "worker_id": "publisher",
            "occurred_at": tables["outbox_delivery_evidence"][1]["occurred_at"],
            "attempts": 0,
        },
    ]

    restored_db = tmp_path / "fenced-restored.db"
    restore_backup(restored_db, backup.backup_path)

    connection = connect(restored_db, require_exists=True)
    try:
        events = [
            dict(row)
            for row in connection.execute(
                """SELECT id, lease_generation, lease_generation_floor, published_at,
                attempts, locked_at, locked_by, dead_lettered_at
                FROM outbox_events ORDER BY id"""
            ).fetchall()
        ]
        evidence = [
            dict(row)
            for row in connection.execute(
                """SELECT evidence_id, event_id, lease_generation, action,
                worker_id, occurred_at, attempts
                FROM outbox_delivery_evidence ORDER BY evidence_id"""
            ).fetchall()
        ]
        expected_events = [
            {
                key: row[key]
                for key in (
                    "id",
                    "lease_generation",
                    "lease_generation_floor",
                    "published_at",
                    "attempts",
                    "locked_at",
                    "locked_by",
                    "dead_lettered_at",
                )
            }
            for row in sorted(tables["outbox_events"], key=lambda row: str(row["id"]))
        ]
        assert events == expected_events
        assert evidence == tables["outbox_delivery_evidence"]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert set(SQLITE_OUTBOX_FENCING_RESTORE_TRIGGER_NAMES) <= _trigger_names(connection)

        with pytest.raises(sqlite3.IntegrityError, match="initial generation"):
            connection.execute(
                """INSERT INTO outbox_events(
                id,event_type,aggregate_type,aggregate_id,payload_json,created_at,available_at,
                lease_generation,lease_generation_floor)
                VALUES('unfenced','test','test','unfenced','{}','2026-10-03T00:00:00Z',
                       '2026-10-03T00:00:00Z',0,2)"""
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="live claimed generation"):
            connection.execute(
                """UPDATE outbox_events SET published_at='2026-10-03T00:00:00Z',
                locked_at=NULL,locked_by=NULL,last_error=NULL WHERE id='pending-event'"""
            )
        connection.rollback()

        repository = SQLiteOutboxRepository(connection)
        claim = repository.claim_pending(worker_id="restored-worker")[0]
        assert claim.id == "pending-event" and claim.lease_generation == 1
        repository.mark_published(
            event_id=claim.id,
            worker_id="restored-worker",
            lease_generation=claim.lease_generation,
        )
    finally:
        connection.close()


@pytest.mark.parametrize("tamper", ["missing_table", "missing_event_column", "missing_evidence_column"])
def test_v53_backup_document_rejects_missing_fencing_contract(
    tmp_path: Path,
    tamper: str,
) -> None:
    source_db = _seed_fenced_database(tmp_path)
    backup = create_backup(source_db, tmp_path / f"v53-{tamper}-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    if tamper == "missing_table":
        payload["tables"].pop("outbox_delivery_evidence")
        expected = "omits required outbox fencing tables"
    elif tamper == "missing_event_column":
        payload["tables"]["outbox_events"][0].pop("lease_generation")
        expected = "omits required outbox fencing columns"
    else:
        payload["tables"]["outbox_delivery_evidence"][0].pop("action")
        expected = "omits required outbox fencing columns"
    _rewrite_backup(backup, payload)
    with pytest.raises(DBBridgeError, match=expected):
        restore_backup(tmp_path / f"{tamper}.db", backup.backup_path)


@pytest.mark.parametrize("damage", ["missing_table", "missing_column", "missing_guard"])
def test_v53_backup_refuses_a_source_without_fencing_contract(tmp_path: Path, damage: str) -> None:
    source_db = _seed_fenced_database(tmp_path)
    connection = connect(source_db, require_exists=True)
    try:
        if damage == "missing_table":
            connection.execute("DROP TABLE outbox_delivery_evidence")
        elif damage == "missing_column":
            for trigger_name in SQLITE_OUTBOX_FENCING_RESTORE_TRIGGER_NAMES:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            connection.execute("ALTER TABLE outbox_events DROP COLUMN lease_generation")
        else:
            connection.execute('DROP TRIGGER "outbox_fencing_guard"')
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(DBBridgeError, match="Unable to create local DB backup"):
        create_backup(source_db, tmp_path / f"missing-{damage}-source-backup")


@pytest.mark.parametrize("tamper", ["missing", "forged"])
def test_v53_restore_rejects_missing_or_forged_retained_evidence(tmp_path: Path, tamper: str) -> None:
    source_db = _seed_fenced_database(tmp_path)
    backup = create_backup(source_db, tmp_path / f"v53-{tamper}-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    evidence = payload["tables"]["outbox_delivery_evidence"]
    if tamper == "missing":
        payload["tables"]["outbox_delivery_evidence"] = []
    else:
        evidence[1]["worker_id"] = "forged-worker"
    _rewrite_backup(backup, payload)

    target = tmp_path / f"{tamper}-evidence-restored.db"
    with pytest.raises(DBBridgeError, match="Outbox fencing backup evidence verification failed"):
        restore_backup(target, backup.backup_path)
    assert not target.exists()
    assert not backup_module._temp_restore_path(target).exists()


def test_v52_backup_without_evidence_restores_then_migrates_to_historical_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_migrations = list(migration_module.MIGRATIONS)
    _set_migrations(monkeypatch, [migration for migration in current_migrations if migration.version <= 52])
    source_db = tmp_path / "v52-source.db"
    migration_module.run_migrations(source_db)
    connection = connect(source_db, require_exists=True)
    try:
        append_outbox_event(
            connection,
            event_id="legacy-claim",
            event_type="synthetic.legacy",
            aggregate_type="synthetic",
            aggregate_id="legacy",
            payload={"synthetic": True},
        )
        connection.execute(
            """UPDATE outbox_events SET locked_at='2099-01-01T00:00:00Z',
            locked_by='legacy-worker' WHERE id='legacy-claim'"""
        )
        connection.commit()
    finally:
        connection.close()

    backup = create_backup(source_db, tmp_path / "v52-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    assert backup.schema_version == 52
    payload["tables"].pop("outbox_delivery_evidence")
    _rewrite_backup(backup, payload)

    _set_migrations(monkeypatch, current_migrations)
    restored_db = tmp_path / "v52-restored.db"
    restore_backup(restored_db, backup.backup_path)

    connection = connect(restored_db, require_exists=True)
    try:
        row = connection.execute(
            "SELECT lease_generation, lease_generation_floor FROM outbox_events WHERE id='legacy-claim'"
        ).fetchone()
        assert row is not None and tuple(row) == (2, 2)
        assert connection.execute("SELECT COUNT(*) FROM outbox_delivery_evidence").fetchone()[0] == 0
        repository = SQLiteOutboxRepository(connection)
        with pytest.raises(OutboxError):
            repository.assert_claim(event_id="legacy-claim", worker_id="legacy-worker", lease_generation=2)
        with pytest.raises(OutboxError):
            repository.mark_published(event_id="legacy-claim", worker_id="legacy-worker", lease_generation=2)
        with pytest.raises(OutboxError):
            repository.mark_failed(
                event_id="legacy-claim",
                worker_id="legacy-worker",
                error="legacy",
                lease_generation=2,
            )
        connection.execute("UPDATE outbox_events SET locked_at='2000-01-01T00:00:00Z' WHERE id='legacy-claim'")
        connection.commit()
        recovered = repository.claim_pending(worker_id="legacy-worker")[0]
        assert recovered.lease_generation == 3
    finally:
        connection.close()
