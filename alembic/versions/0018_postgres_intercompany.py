"""Add tenant-scoped exact intercompany persistence."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_INTERCOMPANY_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_intercompany", "POSTGRES_INTERCOMPANY_SCHEMA_SQL"
)

revision = "0018_postgres_intercompany"
down_revision = "0017_postgres_control_testing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_INTERCOMPANY_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.intercompany_cases;
        DROP TABLE IF EXISTS reconforge.intercompany_transactions;
        """
    )
