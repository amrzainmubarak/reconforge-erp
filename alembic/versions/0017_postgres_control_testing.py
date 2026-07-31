"""Add tenant-scoped control-testing persistence."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_CONTROL_TESTING_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_controls", "POSTGRES_CONTROL_TESTING_SCHEMA_SQL"
)

revision = "0017_postgres_control_testing"
down_revision = "0016_postgres_journals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONTROL_TESTING_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.remediation_plans;
        DROP TABLE IF EXISTS reconforge.control_test_results;
        DROP TABLE IF EXISTS reconforge.control_test_plans;
        DROP TABLE IF EXISTS reconforge.control_library;
        """
    )
