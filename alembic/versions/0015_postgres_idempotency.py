"""Add tenant-scoped generic idempotency records."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_IDEMPOTENCY_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_idempotency", "POSTGRES_IDEMPOTENCY_SCHEMA_SQL"
)

revision = "0015_postgres_idempotency"
down_revision = "0014_postgres_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_IDEMPOTENCY_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.idempotency_records;")
