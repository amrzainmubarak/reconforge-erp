"""Bind replay-verified ownership-change evidence to PostgreSQL close runs."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_LINK_SCHEMA_SQL,
)

revision = "0071_pg_close_ownchg_links"
down_revision = "0070_pg_ownership_change"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_LINK_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.consolidation_close_ownership_change_links) THEN
            RAISE EXCEPTION 'refusing to discard close/ownership-change evidence links';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS consolidation_close_ownership_change_link_guard
            ON reconforge.consolidation_close_ownership_change_links;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_close_ownership_change_link();
        DROP INDEX IF EXISTS reconforge.consolidation_close_ownership_change_links_run_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_close_ownership_change_links;
        """
    )
