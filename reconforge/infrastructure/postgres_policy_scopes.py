"""Immutable PostgreSQL role-permission scope storage."""

from __future__ import annotations

POSTGRES_POLICY_SCOPE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.identity_role_permission_scopes (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^rps-[0-9a-f]{32}$'),
    role_id TEXT NOT NULL,
    permission_name TEXT NOT NULL,
    workspace_id TEXT,
    entity_id TEXT,
    period_id TEXT,
    region_id TEXT,
    data_classification TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    lifecycle_version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    revocation_reason_code TEXT,
    PRIMARY KEY (tenant_id, id),
    CONSTRAINT identity_role_permission_scopes_dimension_required CHECK (
        workspace_id IS NOT NULL OR entity_id IS NOT NULL OR period_id IS NOT NULL
        OR region_id IS NOT NULL OR data_classification IS NOT NULL
    ),
    CONSTRAINT identity_role_permission_scopes_identifier_format CHECK (
        (workspace_id IS NULL OR workspace_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
        AND (entity_id IS NULL OR entity_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
        AND (period_id IS NULL OR period_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
        AND (region_id IS NULL OR region_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
        AND (data_classification IS NULL OR data_classification ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
    ),
    CONSTRAINT identity_role_permission_scopes_lifecycle_version_positive CHECK (lifecycle_version >= 1),
    CONSTRAINT identity_role_permission_scopes_revocation_reason_closed CHECK (
        revocation_reason_code IS NULL OR revocation_reason_code IN (
            'access_change','administrative_cleanup','security_response','user_request'
        )
    ),
    CONSTRAINT identity_role_permission_scopes_state_consistent CHECK (
        (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason_code IS NULL)
        OR (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
            AND revocation_reason_code IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id, role_id, permission_name)
        REFERENCES reconforge.identity_role_permissions(tenant_id, role_id, permission_name)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES reconforge.identity_users(tenant_id, id)
        ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, revoked_by)
        REFERENCES reconforge.identity_users(tenant_id, id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS identity_role_permission_scopes_active_unique
    ON reconforge.identity_role_permission_scopes (
        tenant_id, role_id, permission_name,
        COALESCE(workspace_id, ''), COALESCE(entity_id, ''),
        COALESCE(period_id, ''), COALESCE(region_id, ''),
        COALESCE(data_classification, '')
    ) WHERE active;
CREATE INDEX IF NOT EXISTS identity_role_permission_scopes_lookup
    ON reconforge.identity_role_permission_scopes
        (tenant_id, role_id, permission_name, active, id);

ALTER TABLE reconforge.identity_role_permission_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_role_permission_scopes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.identity_role_permission_scopes;
CREATE POLICY tenant_scope ON reconforge.identity_role_permission_scopes
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE OR REPLACE FUNCTION reconforge.guard_identity_role_permission_scope()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'policy permission scopes are append-only' USING ERRCODE='check_violation';
    END IF;
    IF NEW.tenant_id <> OLD.tenant_id OR NEW.id <> OLD.id
       OR NEW.role_id <> OLD.role_id OR NEW.permission_name <> OLD.permission_name
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.entity_id IS DISTINCT FROM OLD.entity_id
       OR NEW.period_id IS DISTINCT FROM OLD.period_id
       OR NEW.region_id IS DISTINCT FROM OLD.region_id
       OR NEW.data_classification IS DISTINCT FROM OLD.data_classification
       OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by THEN
        RAISE EXCEPTION 'policy permission scope identity is immutable' USING ERRCODE='check_violation';
    END IF;
    IF NOT OLD.active OR NEW.lifecycle_version <> OLD.lifecycle_version + 1
       OR NEW.active OR NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL
       OR NEW.revocation_reason_code IS NULL THEN
        RAISE EXCEPTION 'policy permission scope allows only one active-to-revoked transition'
            USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS identity_role_permission_scope_guard
    ON reconforge.identity_role_permission_scopes;
CREATE TRIGGER identity_role_permission_scope_guard
BEFORE UPDATE OR DELETE ON reconforge.identity_role_permission_scopes
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_identity_role_permission_scope();
"""


POSTGRES_POLICY_SCOPE_AMOUNT_BOUNDS_MIGRATION_SQL = r"""
ALTER TABLE reconforge.identity_role_permission_scopes
    ADD COLUMN IF NOT EXISTS minimum_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS maximum_amount NUMERIC;

ALTER TABLE reconforge.identity_role_permission_scopes
    DROP CONSTRAINT IF EXISTS identity_role_permission_scopes_dimension_required,
    DROP CONSTRAINT IF EXISTS identity_role_permission_scopes_amount_finite,
    DROP CONSTRAINT IF EXISTS identity_role_permission_scopes_amount_order;
ALTER TABLE reconforge.identity_role_permission_scopes
    ADD CONSTRAINT identity_role_permission_scopes_dimension_required CHECK (
        workspace_id IS NOT NULL OR entity_id IS NOT NULL OR period_id IS NOT NULL
        OR region_id IS NOT NULL OR data_classification IS NOT NULL
        OR minimum_amount IS NOT NULL OR maximum_amount IS NOT NULL
    ),
    ADD CONSTRAINT identity_role_permission_scopes_amount_finite CHECK (
        (minimum_amount IS NULL OR (
            minimum_amount::text !~ '^(NaN|Infinity|-Infinity)$'
            AND length(replace(replace(minimum_amount::text, '.', ''), '-', '')) BETWEEN 1 AND 128
        ))
        AND (maximum_amount IS NULL OR (
            maximum_amount::text !~ '^(NaN|Infinity|-Infinity)$'
            AND length(replace(replace(maximum_amount::text, '.', ''), '-', '')) BETWEEN 1 AND 128
        ))
    ),
    ADD CONSTRAINT identity_role_permission_scopes_amount_order CHECK (
        minimum_amount IS NULL OR maximum_amount IS NULL OR minimum_amount <= maximum_amount
    );

DROP INDEX IF EXISTS reconforge.identity_role_permission_scopes_active_unique;
CREATE UNIQUE INDEX identity_role_permission_scopes_active_unique
    ON reconforge.identity_role_permission_scopes (
        tenant_id, role_id, permission_name,
        COALESCE(workspace_id, ''), COALESCE(entity_id, ''),
        COALESCE(period_id, ''), COALESCE(region_id, ''),
        COALESCE(data_classification, ''),
        COALESCE(minimum_amount::text, ''), COALESCE(maximum_amount::text, '')
    ) WHERE active;

CREATE OR REPLACE FUNCTION reconforge.guard_identity_role_permission_scope()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'policy permission scopes are append-only' USING ERRCODE='check_violation';
    END IF;
    IF NEW.tenant_id <> OLD.tenant_id OR NEW.id <> OLD.id
       OR NEW.role_id <> OLD.role_id OR NEW.permission_name <> OLD.permission_name
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.entity_id IS DISTINCT FROM OLD.entity_id
       OR NEW.period_id IS DISTINCT FROM OLD.period_id
       OR NEW.region_id IS DISTINCT FROM OLD.region_id
       OR NEW.data_classification IS DISTINCT FROM OLD.data_classification
       OR NEW.minimum_amount IS DISTINCT FROM OLD.minimum_amount
       OR NEW.maximum_amount IS DISTINCT FROM OLD.maximum_amount
       OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by THEN
        RAISE EXCEPTION 'policy permission scope identity is immutable' USING ERRCODE='check_violation';
    END IF;
    IF NOT OLD.active OR NEW.lifecycle_version <> OLD.lifecycle_version + 1
       OR NEW.active OR NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL
       OR NEW.revocation_reason_code IS NULL THEN
        RAISE EXCEPTION 'policy permission scope allows only one active-to-revoked transition'
            USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
"""


__all__ = ["POSTGRES_POLICY_SCOPE_AMOUNT_BOUNDS_MIGRATION_SQL", "POSTGRES_POLICY_SCOPE_SCHEMA_SQL"]
