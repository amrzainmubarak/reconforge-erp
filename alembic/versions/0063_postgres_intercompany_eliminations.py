"""Add immutable PostgreSQL intercompany elimination evidence."""

from alembic import op
from reconforge.infrastructure.postgres_intercompany_elimination import (
    POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL,
)

revision = "0063_pg_ic_elimination"
down_revision = "0062_pg_outbox_consumer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.intercompany_elimination_artifacts) THEN
            RAISE EXCEPTION 'refusing to discard intercompany elimination evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS intercompany_elimination_artifact_guard
            ON reconforge.intercompany_elimination_artifacts;
        DROP FUNCTION IF EXISTS reconforge.guard_intercompany_elimination_artifact();
        DROP INDEX IF EXISTS reconforge.intercompany_elimination_scope_idx;
        DROP TABLE IF EXISTS reconforge.intercompany_elimination_artifacts;
        """
    )
