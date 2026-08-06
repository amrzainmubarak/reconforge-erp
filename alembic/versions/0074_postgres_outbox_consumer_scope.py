"""Add hierarchy attribution to immutable PostgreSQL outbox receipts."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_OUTBOX_CONSUMER_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_outbox_consumer_scope",
    "POSTGRES_OUTBOX_CONSUMER_SCOPE_SCHEMA_SQL",
)

revision = "0074_pg_outbox_consumer_scope"
down_revision = "0073_pg_outbox_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_OUTBOX_CONSUMER_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.outbox_consumer_receipts) THEN
            RAISE EXCEPTION 'refusing to discard scoped outbox-consumer receipts';
          END IF;
        END $reconforge$;
        """
    )
    op.execute("DROP INDEX IF EXISTS reconforge.outbox_consumer_receipts_scope_event_idx")
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.outbox_consumer_receipts")
    op.execute(
        "CREATE POLICY tenant_scope ON reconforge.outbox_consumer_receipts "
        "USING (tenant_id=current_setting('app.tenant_id',true)) "
        "WITH CHECK (tenant_id=current_setting('app.tenant_id',true))"
    )
    for column in ("legal_entity_id", "organization_id", "workspace_id"):
        op.execute(f"ALTER TABLE reconforge.outbox_consumer_receipts ALTER COLUMN {column} DROP DEFAULT")
        op.execute(f"ALTER TABLE reconforge.outbox_consumer_receipts DROP COLUMN IF EXISTS {column}")
