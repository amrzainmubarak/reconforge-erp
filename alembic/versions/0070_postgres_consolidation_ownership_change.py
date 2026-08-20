"""Persist replayable, non-posting ownership-change evidence."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_ownership_change import (
    POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL,
)

revision = "0070_pg_ownership_change"
down_revision = "0069_pg_close_ppa_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.consolidation_ownership_change_artifacts) THEN
            RAISE EXCEPTION 'refusing to discard consolidation ownership-change evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS consolidation_ownership_change_artifact_guard
            ON reconforge.consolidation_ownership_change_artifacts;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_ownership_change_artifact();
        DROP INDEX IF EXISTS reconforge.consolidation_ownership_change_scope_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_ownership_change_artifacts;
        """
    )
