"""Persist exact amount bounds for role-permission scopes."""

from alembic import op
from reconforge.infrastructure.postgres_policy_scopes import (
    POSTGRES_POLICY_SCOPE_AMOUNT_BOUNDS_MIGRATION_SQL,
)

revision = "0059_pg_policy_amt_bounds"
down_revision = "0058_pg_policy_permission_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_POLICY_SCOPE_AMOUNT_BOUNDS_MIGRATION_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
              SELECT 1 FROM reconforge.identity_role_permission_scopes
              WHERE minimum_amount IS NOT NULL OR maximum_amount IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard policy permission amount-bound evidence';
          END IF;
        END $reconforge$;
        DROP INDEX IF EXISTS reconforge.identity_role_permission_scopes_active_unique;
        ALTER TABLE reconforge.identity_role_permission_scopes
            DROP CONSTRAINT IF EXISTS identity_role_permission_scopes_dimension_required,
            DROP CONSTRAINT IF EXISTS identity_role_permission_scopes_amount_finite,
            DROP CONSTRAINT IF EXISTS identity_role_permission_scopes_amount_order,
            DROP COLUMN IF EXISTS minimum_amount,
            DROP COLUMN IF EXISTS maximum_amount;
        ALTER TABLE reconforge.identity_role_permission_scopes
            ADD CONSTRAINT identity_role_permission_scopes_dimension_required CHECK (
                workspace_id IS NOT NULL OR entity_id IS NOT NULL OR period_id IS NOT NULL
                OR region_id IS NOT NULL OR data_classification IS NOT NULL
            );
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
        CREATE UNIQUE INDEX identity_role_permission_scopes_active_unique
            ON reconforge.identity_role_permission_scopes (
                tenant_id, role_id, permission_name,
                COALESCE(workspace_id, ''), COALESCE(entity_id, ''),
                COALESCE(period_id, ''), COALESCE(region_id, ''),
                COALESCE(data_classification, '')
            ) WHERE active;
        """
    )
