"""Add tenant-scoped PostgreSQL close-control metadata."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_CLOSE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_close",
    "POSTGRES_CLOSE_SCHEMA_SQL",
)

revision = "0006_postgres_close"
down_revision = "0005_postgres_fiscal_periods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create close periods, tasks, dependencies, and RLS policies."""

    op.execute(POSTGRES_CLOSE_SCHEMA_SQL)


def downgrade() -> None:
    """Drop close-control tables in dependency order."""

    op.execute("DROP TABLE IF EXISTS reconforge.close_task_dependencies")
    op.execute("DROP TABLE IF EXISTS reconforge.close_tasks")
    op.execute("DROP TABLE IF EXISTS reconforge.close_periods")
