"""Complete PostgreSQL outbox Application delivery metadata and guards."""

from alembic import op
from reconforge.infrastructure.postgres_outbox import POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL

revision = "0033_postgres_outbox_app"
down_revision = "0032_postgres_exceptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS outbox_application_state_guard ON reconforge.outbox_events")
    op.execute("DROP FUNCTION IF EXISTS reconforge.outbox_application_guard()")
    op.execute("ALTER TABLE reconforge.outbox_events DROP COLUMN IF EXISTS dead_lettered_at")
