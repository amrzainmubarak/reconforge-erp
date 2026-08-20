"""Persist replay-verifiable manufacturing cost-control evidence under PostgreSQL RLS."""

from alembic import op
from reconforge.infrastructure.postgres_manufacturing_cost_control import (
    POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL,
)

revision = "0083_pg_manufacturing"
down_revision = "0082_pg_cert_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.manufacturing_cost_control_runs) THEN
                RAISE EXCEPTION 'refusing to discard manufacturing cost-control evidence';
            END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS manufacturing_cost_control_runs_guard
            ON reconforge.manufacturing_cost_control_runs;
        DROP FUNCTION IF EXISTS reconforge.guard_manufacturing_cost_control_run();
        DROP INDEX IF EXISTS reconforge.manufacturing_cost_control_runs_scope_idx;
        DROP TABLE IF EXISTS reconforge.manufacturing_cost_control_runs;
        """
    )
