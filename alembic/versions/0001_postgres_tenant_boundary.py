"""Create the PostgreSQL tenant/RLS foundation."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_RLS_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres",
    "POSTGRES_RLS_SCHEMA_SQL",
)

revision = "0001_postgres_tenant_boundary"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the idempotent tenant/RLS foundation."""

    op.execute(POSTGRES_RLS_SCHEMA_SQL)


def downgrade() -> None:
    """Drop only this foundation when an operator explicitly requests downgrade."""

    op.execute("DROP SCHEMA IF EXISTS reconforge CASCADE")
