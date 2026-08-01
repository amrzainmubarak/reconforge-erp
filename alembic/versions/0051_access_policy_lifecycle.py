"""Add governed role, policy, and user-role lifecycle metadata."""

from __future__ import annotations

from alembic import op

revision = "0051_access_policy_lifecycle"
down_revision = "0050_identity_admin_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE reconforge.identity_roles
          ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE,
          ADD COLUMN IF NOT EXISTS lifecycle_version BIGINT NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS created_by TEXT,
          ADD COLUMN IF NOT EXISTS retired_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS retired_by TEXT;
        ALTER TABLE reconforge.identity_roles
          DROP CONSTRAINT IF EXISTS identity_roles_lifecycle_version_positive,
          DROP CONSTRAINT IF EXISTS identity_roles_retirement_state_consistent;
        ALTER TABLE reconforge.identity_roles
          ADD CONSTRAINT identity_roles_lifecycle_version_positive CHECK (lifecycle_version >= 1),
          ADD CONSTRAINT identity_roles_retirement_state_consistent CHECK (
            (active AND retired_at IS NULL AND retired_by IS NULL)
            OR (NOT active AND retired_at IS NOT NULL AND retired_by IS NOT NULL)
          );

        ALTER TABLE reconforge.identity_user_roles
          ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE,
          ADD COLUMN IF NOT EXISTS lifecycle_version BIGINT NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          ADD COLUMN IF NOT EXISTS granted_by TEXT,
          ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS revoked_by TEXT,
          ADD COLUMN IF NOT EXISTS revocation_reason_code TEXT;
        ALTER TABLE reconforge.identity_user_roles
          DROP CONSTRAINT IF EXISTS identity_user_roles_lifecycle_version_positive,
          DROP CONSTRAINT IF EXISTS identity_user_roles_revocation_reason_closed,
          DROP CONSTRAINT IF EXISTS identity_user_roles_state_consistent;
        ALTER TABLE reconforge.identity_user_roles
          ADD CONSTRAINT identity_user_roles_lifecycle_version_positive CHECK (lifecycle_version >= 1),
          ADD CONSTRAINT identity_user_roles_revocation_reason_closed CHECK (
            revocation_reason_code IS NULL OR revocation_reason_code IN (
              'access_change','administrative_cleanup','role_retired','security_response','user_request'
            )
          ),
          ADD CONSTRAINT identity_user_roles_state_consistent CHECK (
            (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason_code IS NULL)
            OR (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
                AND revocation_reason_code IS NOT NULL)
          );

        ALTER TABLE reconforge.identity_role_permissions
          ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE,
          ADD COLUMN IF NOT EXISTS lifecycle_version BIGINT NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          ADD COLUMN IF NOT EXISTS granted_by TEXT,
          ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS revoked_by TEXT,
          ADD COLUMN IF NOT EXISTS revocation_reason_code TEXT;
        ALTER TABLE reconforge.identity_role_permissions
          DROP CONSTRAINT IF EXISTS identity_role_permissions_lifecycle_version_positive,
          DROP CONSTRAINT IF EXISTS identity_role_permissions_revocation_reason_closed,
          DROP CONSTRAINT IF EXISTS identity_role_permissions_state_consistent;
        ALTER TABLE reconforge.identity_role_permissions
          ADD CONSTRAINT identity_role_permissions_lifecycle_version_positive CHECK (lifecycle_version >= 1),
          ADD CONSTRAINT identity_role_permissions_revocation_reason_closed CHECK (
            revocation_reason_code IS NULL OR revocation_reason_code IN (
              'access_change','administrative_cleanup','role_retired','security_response','user_request'
            )
          ),
          ADD CONSTRAINT identity_role_permissions_state_consistent CHECK (
            (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason_code IS NULL)
            OR (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
                AND revocation_reason_code IS NOT NULL)
          );

        CREATE INDEX IF NOT EXISTS idx_identity_roles_admin_page
          ON reconforge.identity_roles (tenant_id, active, name, id);
        CREATE INDEX IF NOT EXISTS idx_identity_user_roles_active
          ON reconforge.identity_user_roles (tenant_id, user_id, active, role_id);
        CREATE INDEX IF NOT EXISTS idx_identity_role_permissions_active
          ON reconforge.identity_role_permissions (tenant_id, role_id, active, permission_name);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM reconforge.identity_roles
             WHERE lifecycle_version <> 1 OR NOT active OR created_by IS NOT NULL
                OR retired_at IS NOT NULL OR retired_by IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM reconforge.identity_user_roles
             WHERE lifecycle_version <> 1 OR NOT active OR granted_by IS NOT NULL
                OR revoked_at IS NOT NULL OR revoked_by IS NOT NULL OR revocation_reason_code IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM reconforge.identity_role_permissions
             WHERE lifecycle_version <> 1 OR NOT active OR granted_by IS NOT NULL
                OR revoked_at IS NOT NULL OR revoked_by IS NOT NULL OR revocation_reason_code IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard governed access-policy lifecycle evidence';
          END IF;
        END $reconforge$;

        DROP INDEX IF EXISTS reconforge.idx_identity_role_permissions_active;
        DROP INDEX IF EXISTS reconforge.idx_identity_user_roles_active;
        DROP INDEX IF EXISTS reconforge.idx_identity_roles_admin_page;

        ALTER TABLE reconforge.identity_role_permissions
          DROP CONSTRAINT IF EXISTS identity_role_permissions_state_consistent,
          DROP CONSTRAINT IF EXISTS identity_role_permissions_revocation_reason_closed,
          DROP CONSTRAINT IF EXISTS identity_role_permissions_lifecycle_version_positive,
          DROP COLUMN IF EXISTS revocation_reason_code,
          DROP COLUMN IF EXISTS revoked_by,
          DROP COLUMN IF EXISTS revoked_at,
          DROP COLUMN IF EXISTS granted_by,
          DROP COLUMN IF EXISTS granted_at,
          DROP COLUMN IF EXISTS lifecycle_version,
          DROP COLUMN IF EXISTS active;
        ALTER TABLE reconforge.identity_user_roles
          DROP CONSTRAINT IF EXISTS identity_user_roles_state_consistent,
          DROP CONSTRAINT IF EXISTS identity_user_roles_revocation_reason_closed,
          DROP CONSTRAINT IF EXISTS identity_user_roles_lifecycle_version_positive,
          DROP COLUMN IF EXISTS revocation_reason_code,
          DROP COLUMN IF EXISTS revoked_by,
          DROP COLUMN IF EXISTS revoked_at,
          DROP COLUMN IF EXISTS granted_by,
          DROP COLUMN IF EXISTS granted_at,
          DROP COLUMN IF EXISTS lifecycle_version,
          DROP COLUMN IF EXISTS active;
        ALTER TABLE reconforge.identity_roles
          DROP CONSTRAINT IF EXISTS identity_roles_retirement_state_consistent,
          DROP CONSTRAINT IF EXISTS identity_roles_lifecycle_version_positive,
          DROP COLUMN IF EXISTS retired_by,
          DROP COLUMN IF EXISTS retired_at,
          DROP COLUMN IF EXISTS created_by,
          DROP COLUMN IF EXISTS lifecycle_version,
          DROP COLUMN IF EXISTS active;
        """
    )
