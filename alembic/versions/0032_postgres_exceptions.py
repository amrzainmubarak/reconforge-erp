"""Contract-compatible PostgreSQL exception queue."""

from alembic import op
from reconforge.infrastructure.postgres_exceptions import POSTGRES_EXCEPTIONS_SCHEMA_SQL

revision = "0032_postgres_exceptions"
down_revision = "0031_postgres_evidence_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_EXCEPTIONS_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.exception_queue_history CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.exception_queue_records CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.exception_queue_guard()")
