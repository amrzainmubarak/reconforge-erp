"""Persist replay-verifiable bank-statement control evidence under PostgreSQL RLS."""

from alembic import op
from reconforge.infrastructure.postgres_bank_statement import (
    POSTGRES_BANK_STATEMENT_SCHEMA_SQL,
)

revision = "0084_pg_bank_statement"
down_revision = "0083_pg_manufacturing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_BANK_STATEMENT_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.bank_statement_control_runs) THEN
                RAISE EXCEPTION 'refusing to discard bank-statement evidence';
            END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS bank_statement_control_runs_guard
            ON reconforge.bank_statement_control_runs;
        DROP FUNCTION IF EXISTS reconforge.guard_bank_statement_control_run();
        DROP INDEX IF EXISTS reconforge.bank_statement_control_runs_scope_idx;
        DROP TABLE IF EXISTS reconforge.bank_statement_control_runs;
        """
    )
