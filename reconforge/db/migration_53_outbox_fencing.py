"""Frozen SQLite migration 53: outbox lease fencing and delivery evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator

# This historical artifact deliberately contains the complete guard bundle.
# Future fencing changes require a new migration rather than editing version 53.
SQLITE_OUTBOX_FENCING_UPGRADE_SQL = r"""
ALTER TABLE outbox_events ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0
    CHECK (lease_generation >= 0);
ALTER TABLE outbox_events ADD COLUMN lease_generation_floor INTEGER NOT NULL DEFAULT 0
    CHECK (lease_generation_floor IN (0,2));
-- Existing event history is unknown: reserve the compatibility generation.
UPDATE outbox_events SET lease_generation = 2, lease_generation_floor = 2;
CREATE INDEX idx_outbox_expired_lease
    ON outbox_events(locked_at, created_at, id)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL AND locked_at IS NOT NULL;
CREATE TABLE outbox_delivery_evidence (
    evidence_id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES outbox_events(id) ON DELETE RESTRICT,
    lease_generation INTEGER NOT NULL CHECK (lease_generation >= 0),
    action TEXT NOT NULL CHECK (action IN ('claimed','published','failed','expired','requeued')),
    worker_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    UNIQUE (event_id, lease_generation, action)
);
CREATE INDEX idx_outbox_delivery_evidence_event
    ON outbox_delivery_evidence(event_id, evidence_id);

DROP TRIGGER IF EXISTS outbox_delivery_evidence_append;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_admission;
DROP TRIGGER IF EXISTS outbox_fencing_guard;
DROP TRIGGER IF EXISTS outbox_fencing_insert_guard;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_no_update;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_no_delete;

CREATE TRIGGER outbox_delivery_evidence_no_update BEFORE UPDATE ON outbox_delivery_evidence
BEGIN SELECT RAISE(ABORT, 'outbox delivery evidence is immutable'); END;
CREATE TRIGGER outbox_delivery_evidence_no_delete BEFORE DELETE ON outbox_delivery_evidence
BEGIN SELECT RAISE(ABORT, 'outbox delivery evidence is immutable'); END;

CREATE TRIGGER outbox_fencing_insert_guard BEFORE INSERT ON outbox_events
BEGIN
 SELECT CASE WHEN NEW.lease_generation != 0
   OR NEW.lease_generation_floor != 0
   OR NEW.attempts != 0
   OR NEW.locked_at IS NOT NULL
   OR NEW.locked_by IS NOT NULL
   OR NEW.published_at IS NOT NULL
   OR NEW.dead_lettered_at IS NOT NULL
   OR NEW.last_error IS NOT NULL
 THEN RAISE(ABORT, 'outbox initial generation or delivery state is invalid') END;
END;

CREATE TRIGGER outbox_fencing_guard BEFORE UPDATE ON outbox_events
BEGIN
 SELECT CASE WHEN NEW.lease_generation < OLD.lease_generation
   OR NEW.lease_generation_floor != OLD.lease_generation_floor
   OR NEW.lease_generation < NEW.lease_generation_floor
   OR NEW.lease_generation > OLD.lease_generation + 1
 THEN RAISE(ABORT, 'outbox lease generation is invalid') END;

 SELECT CASE WHEN NOT (
   (
     OLD.published_at IS NULL AND OLD.dead_lettered_at IS NULL
     AND OLD.locked_at IS NULL AND OLD.locked_by IS NULL
     AND NEW.published_at IS NULL AND NEW.dead_lettered_at IS NULL
     AND NEW.locked_at IS NOT NULL AND NEW.locked_by IS NOT NULL
     AND NEW.lease_generation = OLD.lease_generation + 1
     AND NEW.lease_generation > NEW.lease_generation_floor
     AND NEW.attempts = OLD.attempts
   )
   OR (
     OLD.published_at IS NULL AND OLD.dead_lettered_at IS NULL
     AND OLD.locked_at IS NOT NULL AND OLD.locked_by IS NOT NULL
     AND NEW.published_at IS NOT NULL AND NEW.dead_lettered_at IS NULL
     AND NEW.locked_at IS NULL AND NEW.locked_by IS NULL
     AND NEW.lease_generation = OLD.lease_generation
     AND OLD.lease_generation > OLD.lease_generation_floor
     AND OLD.locked_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
     AND NEW.attempts = OLD.attempts AND NEW.last_error IS NULL
   )
   OR (
     OLD.published_at IS NULL AND OLD.dead_lettered_at IS NULL
     AND OLD.locked_at IS NOT NULL AND OLD.locked_by IS NOT NULL
     AND NEW.published_at IS NULL AND NEW.locked_at IS NULL AND NEW.locked_by IS NULL
     AND NEW.lease_generation = OLD.lease_generation
     AND NEW.attempts = OLD.attempts + 1
     AND NEW.last_error IS NOT NULL
     AND (
       (OLD.locked_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        AND NEW.last_error = 'LEASE_EXPIRED')
       OR (OLD.lease_generation > OLD.lease_generation_floor
           AND OLD.locked_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
           AND NEW.last_error != 'LEASE_EXPIRED')
     )
   )
   OR (
     OLD.published_at IS NULL AND OLD.dead_lettered_at IS NOT NULL
     AND OLD.locked_at IS NULL AND OLD.locked_by IS NULL
     AND NEW.published_at IS NULL AND NEW.dead_lettered_at IS NULL
     AND NEW.locked_at IS NULL AND NEW.locked_by IS NULL
     AND NEW.lease_generation = OLD.lease_generation
     AND NEW.attempts = 0 AND NEW.last_error IS NULL
   )
   OR (
     OLD.published_at IS NULL AND OLD.dead_lettered_at IS NULL
     AND OLD.locked_at IS NOT NULL AND OLD.locked_by IS NOT NULL
     AND NEW.published_at IS NULL AND NEW.dead_lettered_at IS NULL
     AND NEW.locked_at IS NOT NULL AND NEW.locked_by IS OLD.locked_by
     AND NEW.locked_at <= OLD.locked_at
     AND NEW.lease_generation = OLD.lease_generation
     AND NEW.attempts = OLD.attempts
     AND NEW.available_at IS OLD.available_at
     AND NEW.last_error IS OLD.last_error
   )
 ) THEN RAISE(ABORT, 'outbox delivery transition requires a live claimed generation') END;
END;

CREATE TRIGGER outbox_delivery_evidence_admission BEFORE INSERT ON outbox_delivery_evidence
BEGIN
 SELECT CASE WHEN NOT EXISTS (
   SELECT 1 FROM outbox_events AS event
   WHERE event.id = NEW.event_id
     AND event.lease_generation = NEW.lease_generation
     AND event.attempts = NEW.attempts
     AND (
       (NEW.action = 'claimed'
        AND event.lease_generation > event.lease_generation_floor
        AND event.locked_at IS NOT NULL AND event.locked_by = NEW.worker_id
        AND event.published_at IS NULL AND event.dead_lettered_at IS NULL)
       OR (NEW.action = 'published'
           AND event.lease_generation > event.lease_generation_floor
           AND event.published_at IS NOT NULL AND event.locked_at IS NULL
           AND event.locked_by IS NULL AND event.dead_lettered_at IS NULL)
       OR (NEW.action = 'failed'
           AND event.lease_generation > event.lease_generation_floor
           AND event.published_at IS NULL AND event.locked_at IS NULL
           AND event.locked_by IS NULL AND event.last_error IS NOT NULL
           AND event.last_error != 'LEASE_EXPIRED')
       OR (NEW.action = 'expired'
           AND event.published_at IS NULL AND event.locked_at IS NULL
           AND event.locked_by IS NULL AND event.last_error = 'LEASE_EXPIRED')
       OR (NEW.action = 'requeued'
           AND event.published_at IS NULL AND event.dead_lettered_at IS NULL
           AND event.locked_at IS NULL AND event.locked_by IS NULL
           AND event.attempts = 0 AND event.last_error IS NULL
           AND (
             (event.lease_generation = event.lease_generation_floor
              AND event.lease_generation_floor = 2)
             OR EXISTS (
               SELECT 1 FROM outbox_delivery_evidence AS prior
               WHERE prior.event_id = event.id
                 AND prior.lease_generation = event.lease_generation
                 AND prior.action IN ('failed', 'expired')
             )
           ))
     )
 ) THEN RAISE(ABORT, 'outbox delivery evidence admission is invalid') END;

 SELECT CASE WHEN NEW.action = 'claimed' AND (
   SELECT COUNT(*) FROM outbox_delivery_evidence AS prior
   JOIN outbox_events AS event ON event.id = NEW.event_id
   WHERE prior.event_id = NEW.event_id
     AND prior.action = 'claimed'
     AND prior.lease_generation > event.lease_generation_floor
     AND prior.lease_generation < NEW.lease_generation
 ) != (
   SELECT event.lease_generation - event.lease_generation_floor - 1
   FROM outbox_events AS event WHERE event.id = NEW.event_id
 ) THEN RAISE(ABORT, 'outbox claimed evidence is discontinuous') END;
END;

CREATE TRIGGER outbox_delivery_evidence_append AFTER UPDATE ON outbox_events
WHEN NEW.lease_generation != OLD.lease_generation
  OR NEW.published_at IS NOT OLD.published_at
  OR NEW.attempts != OLD.attempts
  OR NEW.dead_lettered_at IS NOT OLD.dead_lettered_at
BEGIN
 INSERT INTO outbox_delivery_evidence(event_id, lease_generation, action, worker_id, occurred_at, attempts)
 VALUES(NEW.id, NEW.lease_generation,
   CASE WHEN NEW.lease_generation != OLD.lease_generation THEN 'claimed'
        WHEN NEW.published_at IS NOT NULL THEN 'published'
        WHEN OLD.dead_lettered_at IS NOT NULL AND NEW.dead_lettered_at IS NULL THEN 'requeued'
        WHEN NEW.last_error = 'LEASE_EXPIRED' THEN 'expired' ELSE 'failed' END,
   COALESCE(NEW.locked_by, OLD.locked_by, 'operator'),
   strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), NEW.attempts);
END;
"""


def _statements(script: str) -> Iterator[str]:
    """Yield complete SQLite statements without allowing implicit transaction commits."""

    pending = ""
    for character in script:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            yield pending.strip()
            pending = ""
    if pending.strip():
        raise ValueError("Incomplete outbox fencing migration statement.")


def atomic_outbox_fencing_upgrade(
    connection: sqlite3.Connection,
    *,
    schema_sql: str,
    version: int,
    name: str,
    applied_at: str,
    checkpoint: Callable[[str], None] | None = None,
) -> None:
    """Apply every v53 DDL, watermark and version marker in one writer transaction."""

    if connection.in_transaction:
        raise sqlite3.IntegrityError("Outbox fencing migration requires a clean connection.")
    if type(version) is not int or version != 53 or not schema_sql.strip():
        raise sqlite3.IntegrityError("Invalid outbox fencing migration definition.")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise sqlite3.IntegrityError("Outbox fencing migration requires foreign_keys=ON.")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in _statements(schema_sql):
            connection.execute(statement)
            if "UPDATE outbox_events SET lease_generation" in statement and checkpoint is not None:
                checkpoint("watermarked")
            elif statement.startswith("CREATE TRIGGER outbox_delivery_evidence_append") and checkpoint is not None:
                checkpoint("guards")
        unwatermarked = connection.execute(
            "SELECT COUNT(*) FROM outbox_events WHERE lease_generation<>2 OR lease_generation_floor<>2"
        ).fetchone()[0]
        if int(unwatermarked) != 0:
            raise sqlite3.IntegrityError("Outbox fencing migration did not watermark every retained event.")
        if checkpoint is not None:
            checkpoint("verified")
        connection.execute(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
            (version, name, applied_at),
        )
        connection.execute(f"PRAGMA user_version={version}")
        if checkpoint is not None:
            checkpoint("marked")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
