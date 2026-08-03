"""Persist governed write-back intent history under tenant/workspace RLS."""

from alembic import op
from reconforge.infrastructure.postgres_writeback import POSTGRES_WRITEBACK_SCHEMA_SQL

revision = "0061_pg_writeback_intents"
down_revision = "0060_pg_consolidation_ppa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_WRITEBACK_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.connector_writeback_intents) THEN
            RAISE EXCEPTION 'refusing to discard connector write-back intent evidence';
          END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS connector_writeback_intent_guard
            ON reconforge.connector_writeback_intents;
        DROP FUNCTION IF EXISTS reconforge.guard_connector_writeback_intent();
        DROP INDEX IF EXISTS reconforge.connector_writeback_intents_scope_idx;
        DROP TABLE IF EXISTS reconforge.connector_writeback_intents;
        """
    )
