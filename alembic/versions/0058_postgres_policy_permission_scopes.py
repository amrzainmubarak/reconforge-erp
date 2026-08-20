"""Add immutable entity and period scopes for role permissions."""

from alembic import op
from reconforge.infrastructure.postgres_policy_scopes import POSTGRES_POLICY_SCOPE_SCHEMA_SQL

revision = "0058_pg_policy_permission_scopes"
down_revision = "0057_pg_consol_journal_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_POLICY_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.identity_role_permission_scopes) THEN
            RAISE EXCEPTION 'refusing to discard policy permission scope evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS identity_role_permission_scope_guard
            ON reconforge.identity_role_permission_scopes;
        DROP FUNCTION IF EXISTS reconforge.guard_identity_role_permission_scope();
        DROP INDEX IF EXISTS reconforge.identity_role_permission_scopes_active_unique;
        DROP INDEX IF EXISTS reconforge.identity_role_permission_scopes_lookup;
        DROP TABLE IF EXISTS reconforge.identity_role_permission_scopes;
        """
    )
