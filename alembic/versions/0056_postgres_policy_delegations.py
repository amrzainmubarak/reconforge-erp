"""Add tenant-scoped immutable PostgreSQL policy delegations."""

from alembic import op

from reconforge.infrastructure.postgres_delegations import POSTGRES_DELEGATION_SCHEMA_SQL

revision = "0056_pg_policy_delegations"
down_revision = "0055_pg_consol_close"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_DELEGATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.policy_delegations) THEN
            RAISE EXCEPTION 'refusing to discard policy delegation evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS policy_delegation_guard ON reconforge.policy_delegations;
        DROP FUNCTION IF EXISTS reconforge.guard_policy_delegation_update();
        DROP TABLE IF EXISTS reconforge.policy_delegations;
        """
    )
