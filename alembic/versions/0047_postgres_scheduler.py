"""Add timezone-aware durable schedules and atomic job dispatch evidence."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_SCHEDULER_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_scheduler", "POSTGRES_SCHEDULER_SCHEMA_SQL"
)

revision = "0047_postgres_scheduler"
down_revision = "0046_postgres_scope_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_SCHEDULER_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.schedules LIMIT 1) THEN
            RAISE EXCEPTION '0047 downgrade refuses non-empty scheduler evidence; back up and use an approved data migration';
          END IF;
        END $reconforge$;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS schedule_events_immutable ON reconforge.schedule_events;
        DROP TRIGGER IF EXISTS schedule_dispatches_immutable ON reconforge.schedule_dispatches;
        DROP TRIGGER IF EXISTS schedules_state_guard ON reconforge.schedules;
        DROP TABLE IF EXISTS reconforge.schedule_events;
        DROP TABLE IF EXISTS reconforge.schedule_dispatches;
        DROP TABLE IF EXISTS reconforge.schedules;
        DROP FUNCTION IF EXISTS reconforge.reject_schedule_evidence_mutation();
        DROP FUNCTION IF EXISTS reconforge.schedule_state_guard();
        """
    )
