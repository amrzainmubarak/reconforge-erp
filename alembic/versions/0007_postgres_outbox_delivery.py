"""Add PostgreSQL outbox worker ownership metadata."""

from alembic import op

revision = "0007_postgres_outbox_delivery"
down_revision = "0006_postgres_close"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the worker lease owner and delivery index."""

    op.execute("ALTER TABLE reconforge.outbox_events ADD COLUMN IF NOT EXISTS claimed_by TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_events_claimed "
        "ON reconforge.outbox_events (tenant_id, claimed_by, claimed_at)"
    )


def downgrade() -> None:
    """Remove the worker ownership metadata."""

    op.execute("DROP INDEX IF EXISTS reconforge.idx_outbox_events_claimed")
    op.execute("ALTER TABLE reconforge.outbox_events DROP COLUMN IF EXISTS claimed_by")
