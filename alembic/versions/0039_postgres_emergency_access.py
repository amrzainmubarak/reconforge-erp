"""Add governed temporary emergency access and append-only evidence."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_emergency_access",
    "POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL",
)

revision = "0039_postgres_emergency_access"
down_revision = "0038_postgres_step_up"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.emergency_access_events")
    op.execute("DROP TABLE IF EXISTS reconforge.emergency_access_permissions")
    op.execute("DROP TABLE IF EXISTS reconforge.emergency_access_requests")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_emergency_evidence_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_emergency_access_request_update()")
