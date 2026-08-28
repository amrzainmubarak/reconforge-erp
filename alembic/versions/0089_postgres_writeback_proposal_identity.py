"""Bind every write-back version to one immutable proposal identity."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_writeback",
    "POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL",
)
POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_writeback",
    "POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL",
)

revision = "0089_pg_writeback_identity"
down_revision = "0088_pg_currency_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL)
    op.execute(POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL)


def downgrade() -> None:
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION reconforge.guard_connector_writeback_intent()
        RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'connector write-back intents are immutable' USING ERRCODE='check_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'connector write-back intents cannot be deleted' USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END
        $reconforge$;
        DROP TRIGGER IF EXISTS connector_writeback_intent_guard
            ON reconforge.connector_writeback_intents;
        CREATE TRIGGER connector_writeback_intent_guard
        BEFORE UPDATE OR DELETE ON reconforge.connector_writeback_intents
        FOR EACH ROW EXECUTE FUNCTION reconforge.guard_connector_writeback_intent();
        """
    )
