"""Add tenant-scoped PostgreSQL fiscal-period metadata."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_FISCAL_PERIOD_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_master_data",
    "POSTGRES_FISCAL_PERIOD_SCHEMA_SQL",
)

revision = "0005_postgres_fiscal_periods"
down_revision = "0004_postgres_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install tenant-scoped fiscal-period metadata and forced RLS."""

    op.execute(POSTGRES_FISCAL_PERIOD_SCHEMA_SQL)


def downgrade() -> None:
    """Drop fiscal-period metadata after explicit operator approval."""

    op.execute("DROP TABLE IF EXISTS reconforge.fiscal_periods")
