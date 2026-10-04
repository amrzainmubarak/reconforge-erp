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
LOCK TABLE reconforge.exception_queue_records, reconforge.exception_queue_history IN ACCESS EXCLUSIVE MODE;

ALTER TABLE reconforge.exception_queue_records
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.exception_queue_records
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.exception_queue_records
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.exception_queue_records
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.exception_queue_history
    ADD COLUMN IF NOT EXISTS actor_id TEXT NOT NULL DEFAULT '';
ALTER TABLE reconforge.exception_queue_history
    ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '';

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
        WHERE conname='exception_queue_records_entity_requires_organization'
          AND conrelid='reconforge.exception_queue_records'::regclass
    ) THEN
        ALTER TABLE reconforge.exception_queue_records
            ADD CONSTRAINT exception_queue_records_entity_requires_organization
            CHECK (legal_entity_id IS NULL OR organization_id IS NOT NULL);
    END IF;
END $reconforge$;

CREATE OR REPLACE FUNCTION reconforge.exception_queue_scope_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
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
BEFORE INSERT OR UPDATE OF organization_id,legal_entity_id ON reconforge.exception_queue_records
FOR EACH ROW EXECUTE FUNCTION reconforge.exception_queue_scope_guard();

CREATE OR REPLACE FUNCTION reconforge.exception_queue_review_evidence_guard()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
DECLARE
    queue_record reconforge.exception_queue_records;
BEGIN
    IF NEW.action NOT IN ('exception_review_assigned','exception_review_transition') THEN
        RETURN NEW;
    END IF;
    SELECT * INTO queue_record FROM reconforge.exception_queue_records
    WHERE tenant_id=NEW.tenant_id AND id=NEW.exception_id;
    IF queue_record.id IS NULL OR btrim(NEW.actor_id)='' OR btrim(NEW.actor_label)='' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed exception review requires an authenticated actor';
    END IF;
    IF NEW.action='exception_review_assigned' THEN
        IF lower(btrim(NEW.to_owner))=lower(btrim(queue_record.created_by)) THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator cannot be assigned as reviewer';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT (
        (NEW.from_status='Open' AND NEW.to_status='In Review')
        OR (NEW.from_status='In Review' AND NEW.to_status IN ('Resolved','Accepted Risk'))
        OR (NEW.from_status IN ('Resolved','Accepted Risk') AND NEW.to_status='Closed')
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='governed exception review transition is invalid';
    END IF;
    IF NEW.to_status='Accepted Risk' AND btrim(NEW.reason)='' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='accepted risk requires review reason';
    END IF;
    IF NEW.to_status IN ('Resolved','Accepted Risk','Closed')
       AND (lower(btrim(NEW.actor_id))=lower(btrim(queue_record.created_by))
            OR lower(btrim(NEW.actor_label))=lower(btrim(queue_record.created_by))) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='exception creator cannot make review decision';
    END IF;
    RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS exception_queue_review_evidence_guard ON reconforge.exception_queue_history;
CREATE TRIGGER exception_queue_review_evidence_guard
BEFORE INSERT ON reconforge.exception_queue_history
FOR EACH ROW EXECUTE FUNCTION reconforge.exception_queue_review_evidence_guard();

CREATE INDEX IF NOT EXISTS exception_queue_review_hierarchy_idx
    ON reconforge.exception_queue_records
    (tenant_id,workspace_id,organization_id,legal_entity_id,status,created_at DESC,id);

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

ALTER TABLE reconforge.exception_queue_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_queue_records FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_queue_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.exception_queue_history FORCE ROW LEVEL SECURITY;
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
"""

DOWNGRADE_SQL = r"""
DO $reconforge$
BEGIN
    IF EXISTS (
        SELECT 1 FROM reconforge.exception_queue_records
        WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM reconforge.exception_queue_history
        WHERE actor_id<>'' OR reason<>''
    ) THEN
        RAISE EXCEPTION 'scoped exception review evidence prevents downgrade';
    END IF;
END $reconforge$;

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
DROP TRIGGER IF EXISTS exception_review_permission_role_seed ON reconforge.identity_roles;
DROP TRIGGER IF EXISTS exception_review_permission_tenant_seed ON reconforge.tenants;
DROP FUNCTION IF EXISTS reconforge.seed_exception_review_default_permissions();
DROP INDEX IF EXISTS reconforge.exception_queue_review_hierarchy_idx;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_entity_requires_organization;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_legal_entity_scope_fkey;
ALTER TABLE reconforge.exception_queue_records
    DROP CONSTRAINT IF EXISTS exception_queue_records_organization_scope_fkey;
ALTER TABLE reconforge.exception_queue_history DROP COLUMN IF EXISTS reason;
ALTER TABLE reconforge.exception_queue_history DROP COLUMN IF EXISTS actor_id;
ALTER TABLE reconforge.exception_queue_records DROP COLUMN IF EXISTS legal_entity_id;
ALTER TABLE reconforge.exception_queue_records DROP COLUMN IF EXISTS organization_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
