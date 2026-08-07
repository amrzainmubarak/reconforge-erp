"""Persist replay-verifiable retail settlement evidence under PostgreSQL RLS."""

from alembic import op
from reconforge.infrastructure.postgres_retail_settlement import (
    POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL,
)

revision = "0080_pg_retail_settlement"
down_revision = "0079_pg_job_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.retail_settlement_runs) THEN
                RAISE EXCEPTION 'refusing to discard retail settlement evidence';
            END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS retail_settlement_runs_guard
            ON reconforge.retail_settlement_runs;
        DROP FUNCTION IF EXISTS reconforge.guard_retail_settlement_run();
        DROP INDEX IF EXISTS reconforge.retail_settlement_runs_scope_idx;
        DROP TABLE IF EXISTS reconforge.retail_settlement_runs;
        """
    )
