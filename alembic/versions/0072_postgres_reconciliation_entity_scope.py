"""Add legal-entity attribution to PostgreSQL reconciliation runs."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_RECONCILIATION_ENTITY_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_reconciliation_entity_scope",
    "POSTGRES_RECONCILIATION_ENTITY_SCOPE_SCHEMA_SQL",
)

revision = "0072_pg_recon_entity_scope"
down_revision = "0071_pg_close_ownchg_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_RECONCILIATION_ENTITY_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM reconforge.reconciliation_runs
            WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard reconciliation hierarchy attribution';
          END IF;
        END $reconforge$;
        """
    )
    op.execute("DROP INDEX IF EXISTS reconforge.idx_reconciliation_runs_tenant_entity")
    op.execute(
        "ALTER TABLE reconforge.reconciliation_runs "
        "DROP CONSTRAINT IF EXISTS reconciliation_runs_tenant_legal_entity_fkey"
    )
    op.execute(
        "ALTER TABLE reconforge.reconciliation_runs "
        "DROP CONSTRAINT IF EXISTS reconciliation_runs_tenant_organization_fkey"
    )
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.reconciliation_runs")
    op.execute(
        "CREATE POLICY tenant_scope ON reconforge.reconciliation_runs "
        "USING (tenant_id=current_setting('app.tenant_id',true) AND "
        "(NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR "
        "workspace_id=current_setting('app.workspace_id',true))) "
        "WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND "
        "(NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR "
        "workspace_id=current_setting('app.workspace_id',true)))"
    )
    op.execute("ALTER TABLE reconforge.reconciliation_runs ALTER COLUMN legal_entity_id DROP DEFAULT")
    op.execute("ALTER TABLE reconforge.reconciliation_runs DROP COLUMN IF EXISTS legal_entity_id")
    op.execute("ALTER TABLE reconforge.reconciliation_runs ALTER COLUMN organization_id DROP DEFAULT")
    op.execute("ALTER TABLE reconforge.reconciliation_runs DROP COLUMN IF EXISTS organization_id")
