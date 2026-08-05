"""Persist replayable, non-posting acquisition deferred-tax evidence."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_deferred_tax import (
    POSTGRES_CONSOLIDATION_DEFERRED_TAX_SCHEMA_SQL,
)

revision = "0065_pg_deferred_tax"
down_revision = "0064_pg_close_ic_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_DEFERRED_TAX_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.consolidation_deferred_tax_artifacts) THEN
            RAISE EXCEPTION 'refusing to discard consolidation deferred-tax evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS consolidation_deferred_tax_artifact_guard
            ON reconforge.consolidation_deferred_tax_artifacts;
        DROP FUNCTION IF EXISTS reconforge.guard_consolidation_deferred_tax_artifact();
        DROP INDEX IF EXISTS reconforge.consolidation_deferred_tax_scope_idx;
        DROP TABLE IF EXISTS reconforge.consolidation_deferred_tax_artifacts;
        """
    )
