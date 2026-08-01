"""PostgreSQL approval and certification metadata."""

from alembic import op
from reconforge.infrastructure.postgres_approvals import POSTGRES_APPROVALS_SCHEMA_SQL

revision = "0029_postgres_approvals"
down_revision = "0028_postgres_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_APPROVALS_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.certification_records CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.approval_requests CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.certification_record_guard()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.approval_request_guard()")
