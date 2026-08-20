"""Add immutable tenant-scoped idempotent outbox-consumer receipts."""

from alembic import op
from reconforge.infrastructure.postgres_outbox_consumer import POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL

revision = "0062_pg_outbox_consumer"
down_revision = "0061_pg_writeback_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.outbox_consumer_receipts) THEN
            RAISE EXCEPTION 'refusing to discard idempotent outbox-consumer receipts';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS outbox_consumer_receipt_guard
            ON reconforge.outbox_consumer_receipts;
        DROP FUNCTION IF EXISTS reconforge.guard_outbox_consumer_receipt();
        DROP INDEX IF EXISTS reconforge.outbox_consumer_receipts_event_idx;
        DROP TABLE IF EXISTS reconforge.outbox_consumer_receipts;
        """
    )
