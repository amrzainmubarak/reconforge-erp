"""Persist replayable, non-posting acquisition PPA evidence."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_ppa import POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL

revision = "0060_pg_consolidation_ppa"
down_revision = "0059_pg_policy_amt_bounds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.consolidation_ppa_artifacts) THEN
            RAISE EXCEPTION 'refusing to discard consolidation PPA evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS consolidation_ppa_artifact_guard
            ON reconforge.consolidation_ppa_artifacts;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_ppa_artifact();
        DROP INDEX IF EXISTS reconforge.consolidation_ppa_scope_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_ppa_artifacts;
        """
    )
