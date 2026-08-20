"""Add tenant-scoped PostgreSQL consolidation close control journal."""

from alembic import op
from reconforge.infrastructure.postgres_consolidation_close import POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL

revision = "0055_pg_consol_close"
down_revision = "0054_pg_consol_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS reconforge.consolidation_close_period_events CASCADE;
    DROP TABLE IF EXISTS reconforge.consolidation_close_effects CASCADE;
    DROP TABLE IF EXISTS reconforge.consolidation_close_runs CASCADE;
    DROP TABLE IF EXISTS reconforge.consolidation_close_periods CASCADE;
    """)
