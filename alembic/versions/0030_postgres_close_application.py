"""Contract-compatible PostgreSQL close-management aggregate."""

from alembic import op
from reconforge.infrastructure.postgres_close_application import POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL

revision = "0030_postgres_close_app"
down_revision = "0029_postgres_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.close_application_dependencies CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.close_application_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.close_application_periods CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.close_application_guard()")
