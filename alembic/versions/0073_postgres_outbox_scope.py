"""Add hierarchy attribution to PostgreSQL transactional outbox events."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_OUTBOX_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_outbox_scope",
    "POSTGRES_OUTBOX_SCOPE_SCHEMA_SQL",
)

revision = "0073_pg_outbox_scope"
down_revision = "0072_pg_recon_entity_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_OUTBOX_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM reconforge.outbox_events
            WHERE workspace_id IS NOT NULL
               OR organization_id IS NOT NULL
               OR legal_entity_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard outbox hierarchy attribution';
          END IF;
        END $reconforge$;
        """
    )
    op.execute("DROP INDEX IF EXISTS reconforge.idx_outbox_events_scope_pending")
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.outbox_events")
    op.execute(
        "CREATE POLICY tenant_scope ON reconforge.outbox_events "
        "USING (tenant_id=current_setting('app.tenant_id',true)) "
        "WITH CHECK (tenant_id=current_setting('app.tenant_id',true))"
    )
    for column in ("legal_entity_id", "organization_id", "workspace_id"):
        op.execute(
            f"ALTER TABLE reconforge.outbox_events ALTER COLUMN {column} DROP DEFAULT"
        )
        op.execute(f"ALTER TABLE reconforge.outbox_events DROP COLUMN IF EXISTS {column}")
