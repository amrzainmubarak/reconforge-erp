"""Add optimistic, attributable identity and session lifecycle state."""

from __future__ import annotations

from alembic import op

revision = "0050_identity_admin_lifecycle"
down_revision = "0049_security_center_acl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE reconforge.identity_users
          ADD COLUMN IF NOT EXISTS lifecycle_version BIGINT NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS disabled_by TEXT;
        UPDATE reconforge.identity_users
           SET disabled_at=COALESCE(disabled_at, updated_at)
         WHERE disabled;

        ALTER TABLE reconforge.identity_sessions
          ADD COLUMN IF NOT EXISTS lifecycle_version BIGINT NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS revocation_reason_code TEXT,
          ADD COLUMN IF NOT EXISTS revoked_by TEXT;
        UPDATE reconforge.identity_sessions
           SET revocation_reason_code=COALESCE(revocation_reason_code, 'legacy_or_user_logout')
         WHERE revoked_at IS NOT NULL;

        DO $reconforge$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='identity_users_lifecycle_version_positive') THEN
            ALTER TABLE reconforge.identity_users
              ADD CONSTRAINT identity_users_lifecycle_version_positive CHECK (lifecycle_version >= 1);
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='identity_users_disabled_state_consistent') THEN
            ALTER TABLE reconforge.identity_users
              ADD CONSTRAINT identity_users_disabled_state_consistent CHECK (
                (disabled AND disabled_at IS NOT NULL)
                OR (NOT disabled AND disabled_at IS NULL AND disabled_by IS NULL)
              );
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='identity_sessions_lifecycle_version_positive') THEN
            ALTER TABLE reconforge.identity_sessions
              ADD CONSTRAINT identity_sessions_lifecycle_version_positive CHECK (lifecycle_version >= 1);
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='identity_sessions_revocation_reason_closed') THEN
            ALTER TABLE reconforge.identity_sessions
              ADD CONSTRAINT identity_sessions_revocation_reason_closed CHECK (
                revocation_reason_code IS NULL OR revocation_reason_code IN (
                  'access_change','administrative_cleanup','legacy_or_user_logout',
                  'scim_deactivation','security_response','user_disabled','user_logout','user_request'
                )
              );
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='identity_sessions_revocation_state_consistent') THEN
            ALTER TABLE reconforge.identity_sessions
              ADD CONSTRAINT identity_sessions_revocation_state_consistent CHECK (
                (revoked_at IS NULL AND revocation_reason_code IS NULL AND revoked_by IS NULL)
                OR (revoked_at IS NOT NULL AND revocation_reason_code IS NOT NULL)
              );
          END IF;
        END $reconforge$;

        CREATE INDEX IF NOT EXISTS idx_identity_users_admin_page
          ON reconforge.identity_users (tenant_id, username, id);
        CREATE INDEX IF NOT EXISTS idx_identity_sessions_admin_page
          ON reconforge.identity_sessions (tenant_id, created_at DESC, id DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM reconforge.identity_users
             WHERE lifecycle_version <> 1 OR disabled_by IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM reconforge.identity_sessions
             WHERE lifecycle_version <> 1
                OR revoked_by IS NOT NULL
                OR revocation_reason_code IS DISTINCT FROM
                   CASE WHEN revoked_at IS NULL THEN NULL ELSE 'legacy_or_user_logout' END
          ) THEN
            RAISE EXCEPTION
              '0050 downgrade refused: governed identity lifecycle evidence would be lost';
          END IF;
        END $reconforge$;

        DROP INDEX IF EXISTS reconforge.idx_identity_sessions_admin_page;
        DROP INDEX IF EXISTS reconforge.idx_identity_users_admin_page;
        ALTER TABLE reconforge.identity_sessions
          DROP CONSTRAINT IF EXISTS identity_sessions_revocation_state_consistent,
          DROP CONSTRAINT IF EXISTS identity_sessions_revocation_reason_closed,
          DROP CONSTRAINT IF EXISTS identity_sessions_lifecycle_version_positive,
          DROP COLUMN IF EXISTS revoked_by,
          DROP COLUMN IF EXISTS revocation_reason_code,
          DROP COLUMN IF EXISTS lifecycle_version;
        ALTER TABLE reconforge.identity_users
          DROP CONSTRAINT IF EXISTS identity_users_disabled_state_consistent,
          DROP CONSTRAINT IF EXISTS identity_users_lifecycle_version_positive,
          DROP COLUMN IF EXISTS disabled_by,
          DROP COLUMN IF EXISTS disabled_at,
          DROP COLUMN IF EXISTS lifecycle_version;
        """
    )

