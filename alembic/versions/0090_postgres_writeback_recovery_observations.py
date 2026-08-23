"""Persist immutable, tenant-scoped provider recovery observations."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_WRITEBACK_RECOVERY_OBSERVATIONS_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_writeback",
    "POSTGRES_WRITEBACK_RECOVERY_OBSERVATIONS_SCHEMA_SQL",
)

revision = "0090_pg_writeback_observations"
down_revision = "0089_pg_writeback_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_WRITEBACK_RECOVERY_OBSERVATIONS_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.connector_writeback_recovery_observations;
        DROP FUNCTION IF EXISTS reconforge.guard_connector_writeback_recovery_observation();
        """
    )
