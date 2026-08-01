"""Bind deterministic matching runs to tenant workspaces."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_matching", "POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL"
)
revision = "0023_postgres_matching_app"
down_revision = "0022_postgres_receivables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.matching_run_workspaces")
