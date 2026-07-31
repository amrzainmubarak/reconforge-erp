"""Add tenant-scoped journal-control persistence."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_JOURNAL_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_journals", "POSTGRES_JOURNAL_SCHEMA_SQL"
)

revision = "0016_postgres_journals"
down_revision = "0015_postgres_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_JOURNAL_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.control_exceptions;
        DROP TABLE IF EXISTS reconforge.journal_exceptions;
        DROP TABLE IF EXISTS reconforge.journal_entries;
        """
    )
