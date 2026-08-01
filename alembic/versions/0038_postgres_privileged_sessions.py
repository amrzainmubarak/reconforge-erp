"""Add immutable, session-bound human step-up assertions."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_privileged_sessions",
    "POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL",
)

revision = "0038_postgres_step_up"
down_revision = "0037_postgres_service_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.identity_step_up_assertions")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_step_up_assertion_mutation()")
