"""Scope PostgreSQL exception review and retain governed decision evidence."""

from alembic import op

revision = "0104_pg_exception_review_api"
down_revision = "0103_pg_outbox_fencing"
branch_labels = None
depends_on = None


# This revision owns the historical transition from the original tenant/workspace
# queue to the hierarchy-scoped server-review surface. Later changes must add a
# revision instead of importing mutable runtime schema text here.
UPGRADE_SQL = r"""
DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'exception review migration requires a role that bypasses forced row security';
    END IF;
END $reconforge$;

LOCK TABLE reconforge.exception_queue_records, reconforge.exception_queue_history IN ACCESS EXCLUSIVE MODE;
LOCK TABLE reconforge.tenants, reconforge.identity_roles, reconforge.identity_permissions,
    reconforge.identity_role_permissions IN SHARE ROW EXCLUSIVE MODE;

-- Do not attach GUC defaults while adding these nullable legacy columns. PostgreSQL
-- evaluates an ADD COLUMN default for existing rows; defaults below therefore apply
-- only to records inserted after this revision.
ALTER TABLE reconforge.exception_queue_records
    ADD COLUMN IF NOT EXISTS organization_id TEXT;
ALTER TABLE reconforge.exception_queue_records
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.exception_queue_records
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT;
ALTER TABLE reconforge.exception_queue_records
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.exception_queue_records
    ADD COLUMN IF NOT EXISTS created_by_actor_id TEXT;
ALTER TABLE reconforge.exception_queue_history
    ADD COLUMN IF NOT EXISTS actor_id TEXT NOT NULL DEFAULT '';
ALTER TABLE reconforge.exception_queue_history
    ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '';

-- Replace the pre-0104 record guard before deriving identity: it permits one
-- exact, registered-id fill for a formerly NULL creator identity and rejects
-- every later mutation or label-based substitution.
CREATE OR REPLACE FUNCTION reconforge.exception_queue_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_TABLE_NAME='exception_queue_records' THEN
        IF TG_OP='INSERT' AND NEW.created_by_actor_id IS NULL AND EXISTS (
            SELECT 1 FROM reconforge.identity_users identity_user
            WHERE identity_user.tenant_id=NEW.tenant_id AND identity_user.id=NEW.created_by
        ) THEN
            NEW.created_by_actor_id=NEW.created_by;
        END IF;
        IF TG_OP='UPDATE' AND (
            NEW.workspace_id,NEW.source_type,NEW.source_id,NEW.created_by,NEW.created_at
        ) IS DISTINCT FROM (
            OLD.workspace_id,OLD.source_type,OLD.source_id,OLD.created_by,OLD.created_at
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception source identity is immutable';
        END IF;
        IF TG_OP='UPDATE' AND NEW.created_by_actor_id IS DISTINCT FROM OLD.created_by_actor_id
           AND NOT (
               OLD.created_by_actor_id IS NULL
               AND NEW.created_by_actor_id=OLD.created_by
               AND EXISTS (
                   SELECT 1 FROM reconforge.identity_users identity_user
                   WHERE identity_user.tenant_id=OLD.tenant_id AND identity_user.id=NEW.created_by_actor_id
               )
           ) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator identity is immutable';
        END IF;
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception queue records are retained; update status instead';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP IN ('UPDATE','DELETE') THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception transition history is append-only';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=NEW.tenant_id
          AND queue_record.id=NEW.exception_id
          AND queue_record.status=NEW.to_status
          AND queue_record.owner=NEW.to_owner
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception transition history must match current state';
    END IF;
    RETURN NEW;
END $reconforge$;

-- A label is not an immutable identity. Backfill only an exact immutable user-id
-- match; values without proof remain NULL and governed decisions fail closed
-- instead of treating a mutable label or username as an identity.
WITH creator_candidates AS (
    SELECT queue_record.tenant_id,queue_record.id,MIN(identity_user.id) AS actor_id
    FROM reconforge.exception_queue_records queue_record
    JOIN reconforge.identity_users identity_user
      ON identity_user.tenant_id=queue_record.tenant_id
     AND identity_user.id=queue_record.created_by
    WHERE queue_record.created_by_actor_id IS NULL
    GROUP BY queue_record.tenant_id,queue_record.id
    HAVING COUNT(*)=1
)
UPDATE reconforge.exception_queue_records queue_record
SET created_by_actor_id=creator_candidates.actor_id
FROM creator_candidates
WHERE queue_record.tenant_id=creator_candidates.tenant_id
  AND queue_record.id=creator_candidates.id;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='exception_queue_records_organization_scope_fkey'
          AND conrelid='reconforge.exception_queue_records'::regclass
    ) THEN
        ALTER TABLE reconforge.exception_queue_records
            ADD CONSTRAINT exception_queue_records_organization_scope_fkey
            FOREIGN KEY (tenant_id, organization_id)
            REFERENCES reconforge.organizations(tenant_id, id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='exception_queue_records_legal_entity_scope_fkey'
          AND conrelid='reconforge.exception_queue_records'::regclass
    ) THEN
        ALTER TABLE reconforge.exception_queue_records
            ADD CONSTRAINT exception_queue_records_legal_entity_scope_fkey
            FOREIGN KEY (tenant_id, legal_entity_id)
            REFERENCES reconforge.legal_entities(tenant_id, id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='exception_queue_records_workspace_organization_scope_fkey'
          AND conrelid='reconforge.exception_queue_records'::regclass
    ) THEN
        ALTER TABLE reconforge.exception_queue_records
            ADD CONSTRAINT exception_queue_records_workspace_organization_scope_fkey
            FOREIGN KEY (tenant_id, workspace_id, organization_id)
            REFERENCES reconforge.master_data_workspace_organizations(tenant_id, workspace_id, organization_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='exception_queue_records_creator_actor_fkey'
          AND conrelid='reconforge.exception_queue_records'::regclass
    ) THEN
        ALTER TABLE reconforge.exception_queue_records
            ADD CONSTRAINT exception_queue_records_creator_actor_fkey
            FOREIGN KEY (tenant_id, created_by_actor_id)
            REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='exception_queue_records_entity_requires_organization'
          AND conrelid='reconforge.exception_queue_records'::regclass
    ) THEN
        ALTER TABLE reconforge.exception_queue_records
            ADD CONSTRAINT exception_queue_records_entity_requires_organization
            CHECK (legal_entity_id IS NULL OR organization_id IS NOT NULL);
    END IF;
END $reconforge$;

CREATE OR REPLACE FUNCTION reconforge.exception_queue_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_TABLE_NAME='exception_queue_records' THEN
        IF TG_OP='INSERT' AND NEW.created_by_actor_id IS NULL AND EXISTS (
            SELECT 1 FROM reconforge.identity_users identity_user
            WHERE identity_user.tenant_id=NEW.tenant_id AND identity_user.id=NEW.created_by
        ) THEN
            NEW.created_by_actor_id=NEW.created_by;
        END IF;
        IF TG_OP='UPDATE' AND (
            NEW.workspace_id,NEW.source_type,NEW.source_id,NEW.created_by,NEW.created_at
        ) IS DISTINCT FROM (
            OLD.workspace_id,OLD.source_type,OLD.source_id,OLD.created_by,OLD.created_at
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception source and creator identity are immutable';
        END IF;
        IF TG_OP='UPDATE' AND NEW.created_by_actor_id IS DISTINCT FROM OLD.created_by_actor_id
           AND NOT (
               OLD.created_by_actor_id IS NULL
               AND NEW.created_by_actor_id=OLD.created_by
               AND EXISTS (
                   SELECT 1 FROM reconforge.identity_users identity_user
                   WHERE identity_user.tenant_id=OLD.tenant_id AND identity_user.id=NEW.created_by_actor_id
               )
           ) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator identity is immutable';
        END IF;
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception queue records are retained; update status instead';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP IN ('UPDATE','DELETE') THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception transition history is append-only';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=NEW.tenant_id
          AND queue_record.id=NEW.exception_id
          AND queue_record.status=NEW.to_status
          AND queue_record.owner=NEW.to_owner
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception transition history must match current state';
    END IF;
    RETURN NEW;
END $reconforge$;

CREATE OR REPLACE FUNCTION reconforge.exception_queue_scope_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF NEW.organization_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM reconforge.master_data_workspace_organizations workspace_organization
        WHERE workspace_organization.tenant_id=NEW.tenant_id
          AND workspace_organization.workspace_id=NEW.workspace_id
          AND workspace_organization.organization_id=NEW.organization_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception organization must belong to its workspace';
    END IF;
    IF NEW.legal_entity_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM reconforge.legal_entities entity
        WHERE entity.tenant_id=NEW.tenant_id
          AND entity.id=NEW.legal_entity_id
          AND entity.organization_id=NEW.organization_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception legal entity must belong to its organization';
    END IF;
    RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS exception_queue_scope_guard ON reconforge.exception_queue_records;
CREATE TRIGGER exception_queue_scope_guard
BEFORE INSERT OR UPDATE OF workspace_id,organization_id,legal_entity_id ON reconforge.exception_queue_records
FOR EACH ROW EXECUTE FUNCTION reconforge.exception_queue_scope_guard();

CREATE OR REPLACE FUNCTION reconforge.exception_review_user_is_eligible(
    review_tenant_id TEXT,
    review_workspace_id TEXT,
    review_organization_id TEXT,
    review_legal_entity_id TEXT,
    reviewer_id TEXT
) RETURNS BOOLEAN LANGUAGE sql STABLE AS $reconforge$
    SELECT EXISTS (
        SELECT 1 FROM reconforge.identity_users reviewer
        WHERE reviewer.tenant_id=review_tenant_id AND reviewer.id=reviewer_id AND NOT reviewer.disabled
          AND EXISTS (
              SELECT 1 FROM reconforge.identity_user_roles assignment
              JOIN reconforge.identity_roles role
                ON role.tenant_id=assignment.tenant_id AND role.id=assignment.role_id
              JOIN reconforge.identity_role_permissions permission
                ON permission.tenant_id=assignment.tenant_id AND permission.role_id=assignment.role_id
              WHERE assignment.tenant_id=reviewer.tenant_id AND assignment.user_id=reviewer.id
                AND assignment.active AND role.active AND permission.active
                AND permission.permission_name='exceptions.manage'
          )
          AND EXISTS (
              SELECT 1 FROM reconforge.principal_scope_grants workspace_grant
              WHERE workspace_grant.tenant_id=reviewer.tenant_id
                AND workspace_grant.principal_type='user' AND workspace_grant.principal_id=reviewer.id
                AND workspace_grant.scope_type='workspace' AND workspace_grant.scope_id=review_workspace_id
                AND workspace_grant.revoked_at IS NULL
          )
          AND (review_organization_id IS NULL OR EXISTS (
              SELECT 1 FROM reconforge.principal_scope_grants organization_grant
              WHERE organization_grant.tenant_id=reviewer.tenant_id
                AND organization_grant.principal_type='user' AND organization_grant.principal_id=reviewer.id
                AND organization_grant.scope_type='organization' AND organization_grant.scope_id=review_organization_id
                AND organization_grant.revoked_at IS NULL
          ))
          AND (review_legal_entity_id IS NULL OR EXISTS (
              SELECT 1 FROM reconforge.principal_scope_grants entity_grant
              WHERE entity_grant.tenant_id=reviewer.tenant_id
                AND entity_grant.principal_type='user' AND entity_grant.principal_id=reviewer.id
                AND entity_grant.scope_type='legal_entity' AND entity_grant.scope_id=review_legal_entity_id
                AND entity_grant.revoked_at IS NULL
          ))
    )
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.exception_queue_review_evidence_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
DECLARE
    queue_record reconforge.exception_queue_records;
BEGIN
    IF NEW.action NOT IN ('exception_review_assigned','exception_review_transition') THEN
        RETURN NEW;
    END IF;
    SELECT * INTO queue_record FROM reconforge.exception_queue_records
    WHERE tenant_id=NEW.tenant_id AND id=NEW.exception_id FOR KEY SHARE;
    IF NOT FOUND OR btrim(NEW.actor_id)='' OR btrim(NEW.actor_label)='' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed exception review requires an authenticated actor';
    END IF;
    IF NOT reconforge.exception_review_user_is_eligible(
        queue_record.tenant_id,queue_record.workspace_id,queue_record.organization_id,
        queue_record.legal_entity_id,NEW.actor_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed exception review actor is not eligible for the retained scope';
    END IF;
    IF NEW.action='exception_review_assigned' THEN
        IF queue_record.status='Closed' OR NEW.from_status IS DISTINCT FROM NEW.to_status THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='closed exception cannot be reassigned';
        END IF;
        IF queue_record.created_by_actor_id IS NULL OR btrim(queue_record.created_by_actor_id)='' THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator identity is unavailable for governed assignment';
        END IF;
        IF NEW.to_owner=queue_record.created_by_actor_id THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator cannot be assigned as reviewer';
        END IF;
        IF NOT reconforge.exception_review_user_is_eligible(
            queue_record.tenant_id,queue_record.workspace_id,queue_record.organization_id,
            queue_record.legal_entity_id,NEW.to_owner
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception reviewer is not eligible for the retained scope';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT (
        (NEW.from_status='Open' AND NEW.to_status='In Review')
        OR (NEW.from_status='In Review' AND NEW.to_status IN ('Resolved','Accepted Risk'))
        OR (NEW.from_status IN ('Resolved','Accepted Risk') AND NEW.to_status='Closed')
    ) OR NEW.from_owner IS DISTINCT FROM NEW.to_owner THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed exception review transition is invalid';
    END IF;
    IF NEW.to_status='In Review' AND (
        btrim(queue_record.owner)='' OR NOT reconforge.exception_review_user_is_eligible(
            queue_record.tenant_id,queue_record.workspace_id,queue_record.organization_id,
            queue_record.legal_entity_id,queue_record.owner
        )
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed exception review requires an eligible assigned reviewer';
    END IF;
    IF NEW.to_status='Accepted Risk' AND btrim(NEW.reason)='' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='accepted risk requires review reason';
    END IF;
    IF NEW.to_status IN ('Resolved','Accepted Risk','Closed') THEN
        IF queue_record.created_by_actor_id IS NULL OR btrim(queue_record.created_by_actor_id)='' THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator identity is unavailable for governed decision';
        END IF;
        IF NEW.actor_id=queue_record.created_by_actor_id THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator cannot make review decision';
        END IF;
        IF NEW.actor_id IS DISTINCT FROM queue_record.owner THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed decision requires the assigned reviewer';
        END IF;
    END IF;
    RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS exception_queue_review_evidence_guard ON reconforge.exception_queue_history;
CREATE TRIGGER exception_queue_review_evidence_guard
BEFORE INSERT ON reconforge.exception_queue_history
FOR EACH ROW EXECUTE FUNCTION reconforge.exception_queue_review_evidence_guard();

CREATE TABLE IF NOT EXISTS reconforge.exception_review_evidence (
    tenant_id TEXT NOT NULL,
    history_id TEXT NOT NULL,
    exception_id TEXT NOT NULL,
    audit_event_id TEXT NOT NULL,
    outbox_event_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,history_id),
    UNIQUE (tenant_id,audit_event_id),
    UNIQUE (tenant_id,outbox_event_id),
    FOREIGN KEY (tenant_id,history_id) REFERENCES reconforge.exception_queue_history(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,exception_id) REFERENCES reconforge.exception_queue_records(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS exception_review_evidence_exception_idx
    ON reconforge.exception_review_evidence(tenant_id,exception_id,history_id);
CREATE OR REPLACE FUNCTION reconforge.exception_review_evidence_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
DECLARE
    review_history reconforge.exception_queue_history;
BEGIN
    IF TG_OP<>'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception review evidence is append-only';
    END IF;
    SELECT * INTO review_history FROM reconforge.exception_queue_history
    WHERE tenant_id=NEW.tenant_id AND id=NEW.history_id FOR KEY SHARE;
    IF NOT FOUND OR review_history.exception_id<>NEW.exception_id
       OR review_history.action NOT IN ('exception_review_assigned','exception_review_transition') THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception review evidence history binding is invalid';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM reconforge.domain_audit_events audit_event
        WHERE audit_event.tenant_id=NEW.tenant_id AND audit_event.id=NEW.audit_event_id
          AND audit_event.object_type='exception' AND audit_event.object_id=NEW.exception_id
          AND audit_event.action=review_history.action AND audit_event.actor_user_id=review_history.actor_id
          AND audit_event.metadata_json @> jsonb_build_object('review_history_id',review_history.id)
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception review audit correlation is invalid';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM reconforge.outbox_events outbox_event
        WHERE outbox_event.tenant_id=NEW.tenant_id AND outbox_event.event_id=NEW.outbox_event_id
          AND outbox_event.aggregate_type='exception' AND outbox_event.aggregate_id=NEW.exception_id
          AND outbox_event.event_type=review_history.action
          AND outbox_event.payload @> jsonb_build_object(
              'audit_event_id',NEW.audit_event_id,'review_history_id',review_history.id
          )
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception review outbox correlation is invalid';
    END IF;
    RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS exception_review_evidence_guard ON reconforge.exception_review_evidence;
CREATE TRIGGER exception_review_evidence_guard
BEFORE INSERT OR UPDATE OR DELETE ON reconforge.exception_review_evidence
FOR EACH ROW EXECUTE FUNCTION reconforge.exception_review_evidence_guard();

CREATE INDEX IF NOT EXISTS exception_queue_review_hierarchy_idx
    ON reconforge.exception_queue_records
    (tenant_id,workspace_id,organization_id,legal_entity_id,status,created_at DESC,id);

-- Install both seed triggers while the seed tables are locked, then apply the
-- idempotent current-row backfill. New tenants and roles cannot miss defaults
-- between those two steps.
CREATE OR REPLACE FUNCTION reconforge.seed_exception_review_default_permissions()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_TABLE_NAME='tenants' THEN
        INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES
            (NEW.id,'exceptions.read','Read scoped exception-review records and retained evidence'),
            (NEW.id,'exceptions.manage','Assign and transition scoped exception-review records')
        ON CONFLICT(tenant_id,name) DO NOTHING;
    ELSIF TG_TABLE_NAME='identity_roles' THEN
        INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
        SELECT NEW.tenant_id,NEW.id,permission.name
        FROM reconforge.identity_permissions permission
        WHERE permission.tenant_id=NEW.tenant_id
          AND ((NEW.name IN ('admin','controller','reviewer')
                AND permission.name IN ('exceptions.read','exceptions.manage'))
               OR (NEW.name IN ('preparer','auditor-readonly') AND permission.name='exceptions.read'))
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS exception_review_permission_tenant_seed ON reconforge.tenants;
CREATE TRIGGER exception_review_permission_tenant_seed
AFTER INSERT ON reconforge.tenants
FOR EACH ROW EXECUTE FUNCTION reconforge.seed_exception_review_default_permissions();
DROP TRIGGER IF EXISTS exception_review_permission_role_seed ON reconforge.identity_roles;
CREATE TRIGGER exception_review_permission_role_seed
AFTER INSERT ON reconforge.identity_roles
FOR EACH ROW EXECUTE FUNCTION reconforge.seed_exception_review_default_permissions();

INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
SELECT tenant.id,permission.name,permission.description
FROM reconforge.tenants tenant
CROSS JOIN (VALUES
    ('exceptions.read','Read scoped exception-review records and retained evidence'),
    ('exceptions.manage','Assign and transition scoped exception-review records')
) permission(name,description)
ON CONFLICT(tenant_id,name) DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
SELECT identity_role.tenant_id,identity_role.id,permission.name
FROM reconforge.identity_roles identity_role
JOIN reconforge.identity_permissions permission ON permission.tenant_id=identity_role.tenant_id
WHERE (identity_role.name IN ('admin','controller','reviewer')
       AND permission.name IN ('exceptions.read','exceptions.manage'))
   OR (identity_role.name IN ('preparer','auditor-readonly') AND permission.name='exceptions.read')
ON CONFLICT DO NOTHING;

ALTER TABLE reconforge.exception_queue_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_queue_records FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_queue_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_queue_history FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_review_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_review_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON reconforge.exception_queue_records;
DROP POLICY IF EXISTS tenant_scope ON reconforge.exception_queue_records;
CREATE POLICY tenant_scope ON reconforge.exception_queue_records
USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
         OR workspace_id=current_setting('app.workspace_id',true))
    AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
         OR organization_id=current_setting('app.organization_id',true))
    AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
         OR legal_entity_id=current_setting('app.legal_entity_id',true))
)
WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
         OR workspace_id=current_setting('app.workspace_id',true))
    AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
         OR organization_id=current_setting('app.organization_id',true))
    AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
         OR legal_entity_id=current_setting('app.legal_entity_id',true))
);
DROP POLICY IF EXISTS tenant_isolation ON reconforge.exception_queue_history;
DROP POLICY IF EXISTS tenant_scope ON reconforge.exception_queue_history;
CREATE POLICY tenant_scope ON reconforge.exception_queue_history
USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=exception_queue_history.tenant_id
          AND queue_record.id=exception_queue_history.exception_id
          AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
               OR queue_record.workspace_id=current_setting('app.workspace_id',true))
          AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
               OR queue_record.organization_id=current_setting('app.organization_id',true))
          AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
               OR queue_record.legal_entity_id=current_setting('app.legal_entity_id',true))
    )
)
WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=exception_queue_history.tenant_id
          AND queue_record.id=exception_queue_history.exception_id
          AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
               OR queue_record.workspace_id=current_setting('app.workspace_id',true))
          AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
               OR queue_record.organization_id=current_setting('app.organization_id',true))
          AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
               OR queue_record.legal_entity_id=current_setting('app.legal_entity_id',true))
    )
);
DROP POLICY IF EXISTS tenant_scope ON reconforge.exception_review_evidence;
CREATE POLICY tenant_scope ON reconforge.exception_review_evidence
USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=exception_review_evidence.tenant_id
          AND queue_record.id=exception_review_evidence.exception_id
          AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
               OR queue_record.workspace_id=current_setting('app.workspace_id',true))
          AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
               OR queue_record.organization_id=current_setting('app.organization_id',true))
          AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
               OR queue_record.legal_entity_id=current_setting('app.legal_entity_id',true))
    )
)
WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=exception_review_evidence.tenant_id
          AND queue_record.id=exception_review_evidence.exception_id
          AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
               OR queue_record.workspace_id=current_setting('app.workspace_id',true))
          AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
               OR queue_record.organization_id=current_setting('app.organization_id',true))
          AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
               OR queue_record.legal_entity_id=current_setting('app.legal_entity_id',true))
    )
);
"""

DOWNGRADE_SQL = r"""
DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'exception review migration requires a role that bypasses forced row security';
    END IF;
END $reconforge$;

LOCK TABLE reconforge.exception_queue_records, reconforge.exception_queue_history,
    reconforge.exception_review_evidence IN ACCESS EXCLUSIVE MODE;
LOCK TABLE reconforge.tenants, reconforge.identity_roles, reconforge.identity_permissions,
    reconforge.identity_role_permissions IN SHARE ROW EXCLUSIVE MODE;

DO $reconforge$
BEGIN
    IF EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records
        WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL OR created_by_actor_id IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM reconforge.exception_queue_history
        WHERE actor_id<>'' OR reason<>''
    ) OR EXISTS (
        SELECT 1 FROM reconforge.exception_review_evidence
    ) THEN
        RAISE EXCEPTION 'scoped exception review evidence prevents downgrade';
    END IF;
END $reconforge$;

DROP POLICY IF EXISTS tenant_scope ON reconforge.exception_review_evidence;
DROP TRIGGER IF EXISTS exception_review_evidence_guard ON reconforge.exception_review_evidence;
DROP FUNCTION IF EXISTS reconforge.exception_review_evidence_guard();
DROP TABLE reconforge.exception_review_evidence;

DROP POLICY IF EXISTS tenant_scope ON reconforge.exception_queue_history;
CREATE POLICY tenant_scope ON reconforge.exception_queue_history
USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=exception_queue_history.tenant_id
          AND queue_record.id=exception_queue_history.exception_id
          AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
               OR queue_record.workspace_id=current_setting('app.workspace_id',true))
    )
)
WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=exception_queue_history.tenant_id
          AND queue_record.id=exception_queue_history.exception_id
          AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
               OR queue_record.workspace_id=current_setting('app.workspace_id',true))
    )
);
DROP POLICY IF EXISTS tenant_scope ON reconforge.exception_queue_records;
CREATE POLICY tenant_scope ON reconforge.exception_queue_records
USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
         OR workspace_id=current_setting('app.workspace_id',true))
)
WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
         OR workspace_id=current_setting('app.workspace_id',true))
);
DROP TRIGGER IF EXISTS exception_queue_review_evidence_guard ON reconforge.exception_queue_history;
DROP FUNCTION IF EXISTS reconforge.exception_queue_review_evidence_guard();
DROP TRIGGER IF EXISTS exception_queue_scope_guard ON reconforge.exception_queue_records;
DROP FUNCTION IF EXISTS reconforge.exception_queue_scope_guard();
DROP FUNCTION IF EXISTS reconforge.exception_review_user_is_eligible(TEXT,TEXT,TEXT,TEXT,TEXT);
DROP TRIGGER IF EXISTS exception_review_permission_role_seed ON reconforge.identity_roles;
DROP TRIGGER IF EXISTS exception_review_permission_tenant_seed ON reconforge.tenants;
DROP FUNCTION IF EXISTS reconforge.seed_exception_review_default_permissions();
DROP INDEX IF EXISTS reconforge.exception_queue_review_hierarchy_idx;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_entity_requires_organization;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_creator_actor_fkey;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_workspace_organization_scope_fkey;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_legal_entity_scope_fkey;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_organization_scope_fkey;

CREATE OR REPLACE FUNCTION reconforge.exception_queue_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_TABLE_NAME='exception_queue_records' THEN
        IF TG_OP='UPDATE' AND (NEW.workspace_id,NEW.source_type,NEW.source_id,NEW.created_by,NEW.created_at)
           IS DISTINCT FROM (OLD.workspace_id,OLD.source_type,OLD.source_id,OLD.created_by,OLD.created_at) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception source identity is immutable';
        END IF;
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception queue records are retained; update status instead';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP IN ('UPDATE','DELETE') THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception transition history is append-only';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records queue_record
        WHERE queue_record.tenant_id=NEW.tenant_id AND queue_record.id=NEW.exception_id
          AND queue_record.status=NEW.to_status AND queue_record.owner=NEW.to_owner
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception transition history must match current state';
    END IF;
    RETURN NEW;
END $reconforge$;

ALTER TABLE reconforge.exception_queue_history DROP COLUMN IF EXISTS reason;
ALTER TABLE reconforge.exception_queue_history DROP COLUMN IF EXISTS actor_id;
ALTER TABLE reconforge.exception_queue_records DROP COLUMN IF EXISTS created_by_actor_id;
ALTER TABLE reconforge.exception_queue_records DROP COLUMN IF EXISTS legal_entity_id;
ALTER TABLE reconforge.exception_queue_records DROP COLUMN IF EXISTS organization_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
