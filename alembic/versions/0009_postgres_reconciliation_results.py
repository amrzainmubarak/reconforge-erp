"""Add tenant-scoped reconciliation input, result, and exception persistence."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_RECONCILIATION_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_reconciliation",
    "POSTGRES_RECONCILIATION_SCHEMA_SQL",
)

revision = "0009_postgres_recon_results"
down_revision = "0008_postgres_evidence_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install immutable reconciliation-run persistence and RLS policies."""

    op.execute(POSTGRES_RECONCILIATION_SCHEMA_SQL)


def downgrade() -> None:
    """Remove reconciliation persistence after an explicit operator decision."""

    op.execute("DROP TABLE IF EXISTS reconforge.reconciliation_exceptions")
    op.execute("DROP TABLE IF EXISTS reconforge.reconciliation_results")
    op.execute("DROP TABLE IF EXISTS reconforge.reconciliation_inputs")
    op.execute("DROP TABLE IF EXISTS reconforge.reconciliation_runs")
