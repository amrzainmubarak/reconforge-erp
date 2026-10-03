"""Additive outbox lease fencing and immutable delivery evidence."""

SQLITE_OUTBOX_FENCING_MIGRATION_SQL = """
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
    attempts INTEGER NOT NULL CHECK (attempts >= 0)
);
CREATE INDEX idx_outbox_delivery_evidence_event
    ON outbox_delivery_evidence(event_id, evidence_id);
CREATE TRIGGER outbox_delivery_evidence_no_update BEFORE UPDATE ON outbox_delivery_evidence
BEGIN SELECT RAISE(ABORT, 'outbox delivery evidence is immutable'); END;
CREATE TRIGGER outbox_delivery_evidence_no_delete BEFORE DELETE ON outbox_delivery_evidence
BEGIN SELECT RAISE(ABORT, 'outbox delivery evidence is immutable'); END;
CREATE TRIGGER outbox_fencing_guard BEFORE UPDATE ON outbox_events
WHEN NEW.lease_generation < OLD.lease_generation
  OR NEW.lease_generation_floor != OLD.lease_generation_floor
  OR NEW.lease_generation < NEW.lease_generation_floor
  OR NEW.lease_generation > OLD.lease_generation + 1
  OR (NEW.lease_generation != OLD.lease_generation AND
      (NEW.locked_at IS NULL OR NEW.locked_by IS NULL))
  OR (NEW.locked_by IS NOT NULL AND NEW.locked_by IS NOT OLD.locked_by
      AND NEW.lease_generation != OLD.lease_generation + 1)
BEGIN SELECT RAISE(ABORT, 'outbox lease generation is invalid'); END;
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

POSTGRES_OUTBOX_FENCING_SCHEMA_SQL = """
ALTER TABLE reconforge.outbox_events ADD COLUMN IF NOT EXISTS lease_generation BIGINT
    NOT NULL DEFAULT 0 CHECK (lease_generation >= 0);
ALTER TABLE reconforge.outbox_events ADD COLUMN IF NOT EXISTS lease_generation_floor SMALLINT
    NOT NULL DEFAULT 0 CHECK (lease_generation_floor IN (0,2));
UPDATE reconforge.outbox_events SET lease_generation = 2, lease_generation_floor = 2 WHERE lease_generation = 0
 AND NOT EXISTS (SELECT 1 FROM pg_trigger
 WHERE tgrelid='reconforge.outbox_events'::regclass AND tgname='outbox_fencing_guard');
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
CREATE OR REPLACE FUNCTION reconforge.outbox_fencing_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.lease_generation < OLD.lease_generation
  OR NEW.lease_generation_floor != OLD.lease_generation_floor
  OR NEW.lease_generation < NEW.lease_generation_floor
  OR NEW.lease_generation > OLD.lease_generation + 1
  OR (NEW.lease_generation != OLD.lease_generation AND
      (NEW.status != 'Claimed' OR NEW.claimed_at IS NULL OR NEW.claimed_by IS NULL))
  OR (NEW.claimed_by IS NOT NULL AND NEW.claimed_by IS DISTINCT FROM OLD.claimed_by
      AND NEW.lease_generation != OLD.lease_generation + 1))
 THEN RAISE EXCEPTION 'outbox lease generation is invalid'; END IF;
 IF TG_OP='UPDATE' AND (NEW.lease_generation != OLD.lease_generation OR NEW.status != OLD.status) THEN
  INSERT INTO reconforge.outbox_delivery_evidence(
   tenant_id,event_id,workspace_id,organization_id,legal_entity_id,
   lease_generation,action,worker_id,attempts)
  VALUES(NEW.tenant_id,NEW.event_id,NEW.workspace_id,NEW.organization_id,
   NEW.legal_entity_id,NEW.lease_generation,
   CASE WHEN NEW.lease_generation != OLD.lease_generation THEN 'claimed'
        WHEN NEW.status='Published' THEN 'published'
        WHEN OLD.status='Dead' AND NEW.status='Pending' THEN 'requeued'
        WHEN NEW.last_error='LEASE_EXPIRED' THEN 'expired' ELSE 'failed' END,
   COALESCE(NEW.claimed_by,OLD.claimed_by,'operator'),NEW.attempt_count);
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS outbox_fencing_guard ON reconforge.outbox_events;
CREATE TRIGGER outbox_fencing_guard BEFORE UPDATE ON reconforge.outbox_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_fencing_guard();
CREATE OR REPLACE FUNCTION reconforge.outbox_delivery_evidence_guard()
 RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'outbox delivery evidence is immutable'; END $$;
DROP TRIGGER IF EXISTS outbox_delivery_evidence_immutable ON reconforge.outbox_delivery_evidence;
CREATE TRIGGER outbox_delivery_evidence_immutable BEFORE UPDATE OR DELETE
 ON reconforge.outbox_delivery_evidence FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_delivery_evidence_guard();
"""
