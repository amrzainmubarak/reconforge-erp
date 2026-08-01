"""Keep the administration security overview human-only in PostgreSQL."""

from __future__ import annotations

from alembic import op

revision = "0049_security_center_acl"
down_revision = "0048_postgres_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        DECLARE constraint_name TEXT;
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid='reconforge.service_account_permissions'::regclass
              AND conname='service_account_permissions_human_only'
          ) THEN
            FOR constraint_name IN
              SELECT conname FROM pg_constraint
              WHERE conrelid='reconforge.service_account_permissions'::regclass
                AND contype='c'
                AND pg_get_constraintdef(oid) LIKE '%roles.manage%'
            LOOP
              EXECUTE format(
                'ALTER TABLE reconforge.service_account_permissions DROP CONSTRAINT %I',
                constraint_name
              );
            END LOOP;
            ALTER TABLE reconforge.service_account_permissions
              ADD CONSTRAINT service_account_permissions_human_only CHECK (
                permission_name NOT IN (
                  'roles.manage','users.manage','service_accounts.manage','security.emergency',
                  'security.policy.manage','security.center.read','finance_core.manage','close.manage'
                )
              );
          END IF;
        END $reconforge$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE reconforge.service_account_permissions
          DROP CONSTRAINT IF EXISTS service_account_permissions_human_only;
        ALTER TABLE reconforge.service_account_permissions
          ADD CONSTRAINT service_account_permissions_legacy_human_only CHECK (
            permission_name NOT IN (
              'roles.manage','users.manage','service_accounts.manage','security.emergency',
              'security.policy.manage','finance_core.manage','close.manage'
            )
          );
        """
    )
