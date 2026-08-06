"""Bind replay-verified PPA evidence to PostgreSQL close runs."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_PPA_LINK_SCHEMA_SQL,
)

revision = "0069_pg_close_ppa_links"
down_revision = "0068_pg_close_deferred_tax_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the append-only close/PPA evidence link relation."""

    op.execute(POSTGRES_CONSOLIDATION_PPA_LINK_SCHEMA_SQL)


def downgrade() -> None:
    """Refuse to discard evidence links until the table is empty."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.consolidation_close_ppa_links LIMIT 1) THEN
                RAISE EXCEPTION 'refusing to discard close/PPA evidence links';
            END IF;
        END $$;
        DROP TRIGGER IF EXISTS consolidation_close_ppa_links_immutable
            ON reconforge.consolidation_close_ppa_links;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_close_ppa_link();
        DROP INDEX IF EXISTS reconforge.consolidation_close_ppa_links_run_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_close_ppa_links;
        """
    )
