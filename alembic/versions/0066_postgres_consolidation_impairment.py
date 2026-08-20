"""Persist replayable, non-posting consolidation impairment evidence."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_impairment import (
    POSTGRES_CONSOLIDATION_IMPAIRMENT_SCHEMA_SQL,
)

revision = "0066_pg_impairment"
down_revision = "0065_pg_deferred_tax"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_IMPAIRMENT_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.consolidation_impairment_artifacts) THEN
            RAISE EXCEPTION 'refusing to discard consolidation impairment evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS consolidation_impairment_artifact_guard
            ON reconforge.consolidation_impairment_artifacts;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_impairment_artifact();
        DROP INDEX IF EXISTS reconforge.consolidation_impairment_scope_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_impairment_artifacts;
        """
    )
