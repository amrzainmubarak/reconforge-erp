"""Freeze outbox lease fencing and immutable delivery evidence after budget control."""

from alembic import op

revision = "0103_pg_outbox_fencing"
down_revision = "0102_pg_budget_control"
branch_labels = None
depends_on = None


# This revision owns its complete historical DDL. Future fencing changes must
# use a later revision; it never imports mutable infrastructure schema text.
UPGRADE_SQL = r"""
DO $reconforge$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_roles
   WHERE rolname = current_user AND (rolsuper OR rolbypassrls)
 ) THEN
   RAISE EXCEPTION 'outbox fencing migration requires a role that bypasses forced row security';
 END IF;
END $reconforge$;

LOCK TABLE reconforge.outbox_events IN ACCESS EXCLUSIVE MODE;

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

DOWNGRADE_SQL = r"""
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

DROP TRIGGER outbox_delivery_evidence_immutable ON reconforge.outbox_delivery_evidence;
DROP TRIGGER outbox_delivery_evidence_admission ON reconforge.outbox_delivery_evidence;
DROP TRIGGER outbox_delivery_evidence_append ON reconforge.outbox_events;
DROP TRIGGER outbox_fencing_guard ON reconforge.outbox_events;
DROP FUNCTION reconforge.outbox_delivery_evidence_guard();
DROP FUNCTION reconforge.outbox_delivery_evidence_admission_guard();
DROP FUNCTION reconforge.outbox_delivery_evidence_append();
DROP FUNCTION reconforge.outbox_fencing_guard();
DROP TABLE reconforge.outbox_delivery_evidence;
DROP INDEX reconforge.idx_outbox_expired_lease;
ALTER TABLE reconforge.outbox_events DROP COLUMN lease_generation_floor;
ALTER TABLE reconforge.outbox_events DROP COLUMN lease_generation;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
