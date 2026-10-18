"""Additive outbox lease fencing and immutable delivery evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.db.migration_53_outbox_fencing import SQLITE_OUTBOX_FENCING_UPGRADE_SQL


class PostgresOutboxFencingMigrationError(RuntimeError):
    """The migration identity cannot safely watermark every tenant row."""


# Restore tooling may reinstall this set only inside an unpublished temporary
# SQLite database, after it has loaded parent rows and verified all evidence.
# It must never remove these triggers from a database workers can reach.
SQLITE_OUTBOX_FENCING_RESTORE_TRIGGER_NAMES = (
    "outbox_delivery_evidence_append",
    "outbox_delivery_evidence_admission",
    "outbox_fencing_guard",
    "outbox_fencing_insert_guard",
    "outbox_delivery_evidence_no_update",
    "outbox_delivery_evidence_no_delete",
)

SQLITE_OUTBOX_FENCING_GUARD_SQL = """
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

# Compatibility tests need the exact registered migration content. The frozen
# SQLite artifact is the source of truth; restore still uses the current guard
# bundle only inside an unpublished temporary database.
SQLITE_OUTBOX_FENCING_MIGRATION_SQL = SQLITE_OUTBOX_FENCING_UPGRADE_SQL


POSTGRES_OUTBOX_FENCING_SCHEMA_SQL = """
DO $reconforge$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_roles
   WHERE rolname = current_user AND (rolsuper OR rolbypassrls)
 ) THEN
   RAISE EXCEPTION 'outbox fencing migration requires a role that bypasses forced row security';
 END IF;
END $reconforge$;

ALTER TABLE reconforge.outbox_events ADD COLUMN IF NOT EXISTS lease_generation BIGINT
    NOT NULL DEFAULT 0 CHECK (lease_generation >= 0);
ALTER TABLE reconforge.outbox_events ADD COLUMN IF NOT EXISTS lease_generation_floor SMALLINT
    NOT NULL DEFAULT 0 CHECK (lease_generation_floor IN (0,2));
UPDATE reconforge.outbox_events SET lease_generation = 2, lease_generation_floor = 2
 WHERE NOT EXISTS (
   SELECT 1 FROM pg_trigger
   WHERE tgrelid='reconforge.outbox_events'::regclass AND tgname='outbox_fencing_guard'
 );
DO $reconforge$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_trigger
   WHERE tgrelid='reconforge.outbox_events'::regclass AND tgname='outbox_fencing_guard'
 ) AND EXISTS (
   SELECT 1 FROM reconforge.outbox_events
   WHERE lease_generation <> 2 OR lease_generation_floor <> 2
 ) THEN
   RAISE EXCEPTION 'outbox fencing migration did not watermark every existing event';
 END IF;
END $reconforge$;

CREATE INDEX IF NOT EXISTS idx_outbox_expired_lease
    ON reconforge.outbox_events(tenant_id, claimed_at, created_at, event_id)
    WHERE status = 'Claimed';
CREATE TABLE IF NOT EXISTS reconforge.outbox_delivery_evidence (
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    workspace_id TEXT,
    organization_id TEXT,
    legal_entity_id TEXT,
    lease_generation BIGINT NOT NULL CHECK (lease_generation >= 0),
    action TEXT NOT NULL CHECK (action IN ('claimed','published','failed','expired','requeued')),
    worker_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    PRIMARY KEY (tenant_id,event_id,lease_generation,action),
    FOREIGN KEY (tenant_id,event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE INDEX IF NOT EXISTS idx_outbox_delivery_evidence_event
    ON reconforge.outbox_delivery_evidence(tenant_id,event_id,occurred_at,lease_generation,action);
ALTER TABLE reconforge.outbox_delivery_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.outbox_delivery_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.outbox_delivery_evidence;
CREATE POLICY tenant_scope ON reconforge.outbox_delivery_evidence
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR legal_entity_id=current_setting('app.legal_entity_id',true)));
REVOKE INSERT, UPDATE, DELETE ON TABLE reconforge.outbox_delivery_evidence FROM PUBLIC;

CREATE OR REPLACE FUNCTION reconforge.outbox_fencing_guard() RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
 IF TG_OP = 'INSERT' THEN
  IF NEW.lease_generation <> 0 OR NEW.lease_generation_floor <> 0
    OR NEW.status <> 'Pending' OR NEW.attempt_count <> 0
    OR NEW.claimed_at IS NOT NULL OR NEW.claimed_by IS NOT NULL
    OR NEW.published_at IS NOT NULL OR NEW.dead_lettered_at IS NOT NULL
    OR NEW.last_error IS NOT NULL
  THEN RAISE EXCEPTION 'outbox initial generation or delivery state is invalid'; END IF;
  RETURN NEW;
 END IF;

 IF NEW.lease_generation < OLD.lease_generation
  OR NEW.lease_generation_floor <> OLD.lease_generation_floor
  OR NEW.lease_generation < NEW.lease_generation_floor
  OR NEW.lease_generation > OLD.lease_generation + 1
 THEN RAISE EXCEPTION 'outbox lease generation is invalid'; END IF;

 IF NOT (
   (OLD.status='Pending' AND NEW.status='Claimed'
    AND NEW.lease_generation=OLD.lease_generation+1
    AND NEW.lease_generation>NEW.lease_generation_floor
    AND NEW.attempt_count=OLD.attempt_count+1
    AND NEW.claimed_at IS NOT NULL AND NEW.claimed_at>clock_timestamp() AND NEW.claimed_by IS NOT NULL
    AND NEW.published_at IS NULL AND NEW.dead_lettered_at IS NULL)
   OR (OLD.status='Claimed' AND NEW.status='Published'
       AND NEW.lease_generation=OLD.lease_generation
       AND OLD.lease_generation>OLD.lease_generation_floor
       AND OLD.claimed_at>clock_timestamp()
       AND NEW.attempt_count=OLD.attempt_count AND NEW.claimed_at IS NULL AND NEW.claimed_by IS NULL
       AND NEW.published_at IS NOT NULL AND NEW.dead_lettered_at IS NULL AND NEW.last_error IS NULL)
   OR (OLD.status='Claimed' AND NEW.status IN ('Pending','Dead')
       AND NEW.lease_generation=OLD.lease_generation AND NEW.attempt_count=OLD.attempt_count
       AND NEW.claimed_at IS NULL AND NEW.claimed_by IS NULL AND NEW.published_at IS NULL
       AND NEW.last_error IS NOT NULL
       AND ((OLD.claimed_at<=clock_timestamp() AND NEW.last_error='LEASE_EXPIRED')
            OR (OLD.lease_generation>OLD.lease_generation_floor
                AND OLD.claimed_at>clock_timestamp() AND NEW.last_error<>'LEASE_EXPIRED')))
   OR (OLD.status='Dead' AND NEW.status='Pending'
       AND NEW.lease_generation=OLD.lease_generation AND NEW.attempt_count=0
       AND NEW.claimed_at IS NULL AND NEW.claimed_by IS NULL AND NEW.published_at IS NULL
       AND NEW.dead_lettered_at IS NULL AND NEW.last_error IS NULL)
   OR (OLD.status='Claimed' AND NEW.status='Claimed'
       AND NEW.lease_generation=OLD.lease_generation AND NEW.attempt_count=OLD.attempt_count
       AND NEW.claimed_by IS NOT DISTINCT FROM OLD.claimed_by
       AND NEW.claimed_at IS NOT NULL AND NEW.claimed_at<=OLD.claimed_at
       AND NEW.published_at IS NOT DISTINCT FROM OLD.published_at
       AND NEW.dead_lettered_at IS NOT DISTINCT FROM OLD.dead_lettered_at
       AND NEW.available_at IS NOT DISTINCT FROM OLD.available_at
       AND NEW.last_error IS NOT DISTINCT FROM OLD.last_error)
 ) THEN RAISE EXCEPTION 'outbox delivery transition requires a live claimed generation'; END IF;
 RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS outbox_fencing_guard ON reconforge.outbox_events;
CREATE TRIGGER outbox_fencing_guard BEFORE INSERT OR UPDATE ON reconforge.outbox_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_fencing_guard();

CREATE OR REPLACE FUNCTION reconforge.outbox_delivery_evidence_admission_guard()
 RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = reconforge, pg_catalog AS $reconforge$
DECLARE
 parent reconforge.outbox_events%ROWTYPE;
 preceding_claims BIGINT;
BEGIN
 IF pg_trigger_depth() <> 2 THEN
   RAISE EXCEPTION 'outbox delivery evidence inserts are restricted to the transition trigger';
 END IF;
 SELECT * INTO parent FROM reconforge.outbox_events
  WHERE tenant_id=NEW.tenant_id AND event_id=NEW.event_id FOR KEY SHARE;
 IF NOT FOUND
  OR NEW.workspace_id IS DISTINCT FROM parent.workspace_id
  OR NEW.organization_id IS DISTINCT FROM parent.organization_id
  OR NEW.legal_entity_id IS DISTINCT FROM parent.legal_entity_id
  OR NEW.lease_generation <> parent.lease_generation
  OR NEW.attempts <> parent.attempt_count
  OR btrim(NEW.worker_id) = ''
 THEN RAISE EXCEPTION 'outbox delivery evidence parent binding is invalid'; END IF;

 IF NOT (
   (NEW.action='claimed' AND parent.status='Claimed'
    AND parent.lease_generation>parent.lease_generation_floor
    AND parent.claimed_at IS NOT NULL AND parent.claimed_by=NEW.worker_id)
   OR (NEW.action='published' AND parent.status='Published'
       AND parent.lease_generation>parent.lease_generation_floor AND parent.published_at IS NOT NULL)
   OR (NEW.action='failed' AND parent.status IN ('Pending','Dead')
       AND parent.lease_generation>parent.lease_generation_floor
       AND parent.last_error IS NOT NULL AND parent.last_error<>'LEASE_EXPIRED')
   OR (NEW.action='expired' AND parent.status IN ('Pending','Dead')
       AND parent.last_error='LEASE_EXPIRED')
   OR (NEW.action='requeued' AND parent.status='Pending' AND parent.attempt_count=0
       AND parent.last_error IS NULL
       AND ((parent.lease_generation=parent.lease_generation_floor AND parent.lease_generation_floor=2)
            OR EXISTS (SELECT 1 FROM reconforge.outbox_delivery_evidence AS prior
                       WHERE prior.tenant_id=NEW.tenant_id AND prior.event_id=NEW.event_id
                         AND prior.lease_generation=NEW.lease_generation
                         AND prior.action IN ('failed','expired'))))
 ) THEN RAISE EXCEPTION 'outbox delivery evidence admission is invalid'; END IF;

 IF NEW.action='claimed' THEN
   SELECT COUNT(*) INTO preceding_claims FROM reconforge.outbox_delivery_evidence
    WHERE tenant_id=NEW.tenant_id AND event_id=NEW.event_id AND action='claimed'
      AND lease_generation>parent.lease_generation_floor AND lease_generation<NEW.lease_generation;
   IF preceding_claims <> NEW.lease_generation-parent.lease_generation_floor-1 THEN
     RAISE EXCEPTION 'outbox claimed evidence is discontinuous';
   END IF;
 END IF;
 RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_admission ON reconforge.outbox_delivery_evidence;
CREATE TRIGGER outbox_delivery_evidence_admission BEFORE INSERT ON reconforge.outbox_delivery_evidence
 FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_delivery_evidence_admission_guard();

CREATE OR REPLACE FUNCTION reconforge.outbox_delivery_evidence_append()
 RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = reconforge, pg_catalog AS $reconforge$
BEGIN
 IF NEW.lease_generation <> OLD.lease_generation OR NEW.status <> OLD.status THEN
  INSERT INTO reconforge.outbox_delivery_evidence(
   tenant_id,event_id,workspace_id,organization_id,legal_entity_id,
   lease_generation,action,worker_id,attempts)
  VALUES(NEW.tenant_id,NEW.event_id,NEW.workspace_id,NEW.organization_id,
   NEW.legal_entity_id,NEW.lease_generation,
   CASE WHEN NEW.lease_generation <> OLD.lease_generation THEN 'claimed'
        WHEN NEW.status='Published' THEN 'published'
        WHEN OLD.status='Dead' AND NEW.status='Pending' THEN 'requeued'
        WHEN NEW.last_error='LEASE_EXPIRED' THEN 'expired' ELSE 'failed' END,
   COALESCE(NEW.claimed_by,OLD.claimed_by,'operator'),NEW.attempt_count);
 END IF;
 RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_append ON reconforge.outbox_events;
CREATE TRIGGER outbox_delivery_evidence_append AFTER UPDATE ON reconforge.outbox_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_delivery_evidence_append();

CREATE OR REPLACE FUNCTION reconforge.outbox_delivery_evidence_guard()
 RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN RAISE EXCEPTION 'outbox delivery evidence is immutable'; END $reconforge$;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_immutable ON reconforge.outbox_delivery_evidence;
CREATE TRIGGER outbox_delivery_evidence_immutable BEFORE UPDATE OR DELETE
 ON reconforge.outbox_delivery_evidence FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_delivery_evidence_guard();
"""


POSTGRES_OUTBOX_FENCING_DOWNGRADE_ADMISSION_SQL = """
DO $reconforge$
BEGIN
 IF EXISTS (SELECT 1 FROM reconforge.outbox_delivery_evidence) THEN
   RAISE EXCEPTION 'outbox fencing downgrade refused: delivery evidence is retained';
 END IF;
 IF EXISTS (
   SELECT 1 FROM reconforge.outbox_events
   WHERE lease_generation <> 0 OR lease_generation_floor <> 0
 ) THEN
   RAISE EXCEPTION 'outbox fencing downgrade refused: non-default generations are retained';
 END IF;
END $reconforge$;
"""


def _migration_row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _migration_execute(connection: Any, statement: str) -> Any:
    execute_driver_sql = getattr(connection, "exec_driver_sql", None)
    if callable(execute_driver_sql):
        return execute_driver_sql(statement)
    return connection.execute(statement)


def verify_postgres_outbox_fencing_migration_identity(connection: Any) -> None:
    """Fail before watermarking when the effective role cannot bypass forced RLS."""
    row = _migration_execute(
        connection,
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user",
    ).fetchone()
    if row is None or not (
        bool(_migration_row_value(row, "rolsuper", 0))
        or bool(_migration_row_value(row, "rolbypassrls", 1))
    ):
        raise PostgresOutboxFencingMigrationError(
            "Outbox fencing migration requires an effective role that bypasses forced row security."
        )


def verify_postgres_outbox_fencing_upgrade_coverage(connection: Any) -> None:
    """Require the just-completed upgrade to reserve every pre-existing row at 2/2."""
    row = _migration_execute(
        connection,
        """SELECT COUNT(*) AS unwatermarked FROM reconforge.outbox_events
        WHERE lease_generation <> 2 OR lease_generation_floor <> 2""",
    ).fetchone()
    if row is None or int(_migration_row_value(row, "unwatermarked", 0) or 0) != 0:
        raise PostgresOutboxFencingMigrationError(
            "Outbox fencing migration did not watermark every pre-existing event at 2/2."
        )
