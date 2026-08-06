"""Bind replay-verified impairment evidence to PostgreSQL close runs."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_IMPAIRMENT_LINK_SCHEMA_SQL,
)

revision = "0067_pg_close_impairment_links"
down_revision = "0066_pg_impairment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_IMPAIRMENT_LINK_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.consolidation_close_impairment_links) THEN
            RAISE EXCEPTION 'refusing to discard close/impairment evidence links';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS consolidation_close_impairment_link_guard
            ON reconforge.consolidation_close_impairment_links;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_close_impairment_link();
        DROP INDEX IF EXISTS reconforge.consolidation_close_impairment_links_run_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_close_impairment_links;
        """
    )
