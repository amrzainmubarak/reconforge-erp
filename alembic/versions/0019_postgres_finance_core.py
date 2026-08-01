"""Add tenant-scoped governed Finance Core persistence."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_FINANCE_CORE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_finance_core", "POSTGRES_FINANCE_CORE_SCHEMA_SQL"
)

revision = "0019_postgres_finance_core"
down_revision = "0018_postgres_intercompany"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_FINANCE_CORE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.finance_entry_line_dimensions;
        DROP TABLE IF EXISTS reconforge.finance_entry_lines;
        DROP TABLE IF EXISTS reconforge.finance_entries;
        DROP TABLE IF EXISTS reconforge.finance_journals;
        DROP TABLE IF EXISTS reconforge.finance_dimension_values;
        DROP TABLE IF EXISTS reconforge.finance_dimensions;
        DROP TABLE IF EXISTS reconforge.finance_accounts;
        DROP TABLE IF EXISTS reconforge.finance_charts;
        """
    )
