"""Add tenant-scoped operational diagnostic records."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_OPERATIONS_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_operations", "POSTGRES_OPERATIONS_SCHEMA_SQL"
)

revision = "0014_postgres_operations"
down_revision = "0013_postgres_domain_uow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_OPERATIONS_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.ops_error_records;
        DROP TABLE IF EXISTS reconforge.ops_job_history;
        """
    )
