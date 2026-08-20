"""Add hierarchy attribution to impairment and deferred-tax evidence."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_consolidation_impairment_deferred_tax_scope",
    "POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL",
)

revision = "0077_pg_imp_tax_scope"
down_revision = "0076_pg_consolidation_ppa_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM reconforge.consolidation_impairment_artifacts
            WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard consolidation impairment hierarchy attribution';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM reconforge.consolidation_deferred_tax_artifacts
            WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard consolidation deferred-tax hierarchy attribution';
          END IF;
        END $reconforge$;
        """
    )
    op.execute("DROP INDEX IF EXISTS reconforge.consolidation_impairment_hierarchy_scope_idx")
    op.execute("DROP INDEX IF EXISTS reconforge.consolidation_deferred_tax_hierarchy_scope_idx")
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_impairment_artifacts")
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_deferred_tax_artifacts")
    op.execute("CREATE POLICY tenant_scope ON reconforge.consolidation_impairment_artifacts USING (tenant_id=current_setting('app.tenant_id',true)) WITH CHECK (tenant_id=current_setting('app.tenant_id',true))")
    op.execute("CREATE POLICY tenant_scope ON reconforge.consolidation_deferred_tax_artifacts USING (tenant_id=current_setting('app.tenant_id',true)) WITH CHECK (tenant_id=current_setting('app.tenant_id',true))")
    op.execute("ALTER TABLE reconforge.consolidation_impairment_artifacts DROP CONSTRAINT IF EXISTS consolidation_impairment_scope_result_digest_key")
    op.execute("ALTER TABLE reconforge.consolidation_impairment_artifacts ADD CONSTRAINT consolidation_impairment_artifacts_tenant_id_result_digest_key UNIQUE (tenant_id,result_digest)")
    op.execute("ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DROP CONSTRAINT IF EXISTS consolidation_deferred_tax_scope_result_digest_key")
    op.execute("ALTER TABLE reconforge.consolidation_deferred_tax_artifacts ADD CONSTRAINT consolidation_deferred_tax_artifacts_tenant_id_result_digest_key UNIQUE (tenant_id,result_digest)")
    op.execute("ALTER TABLE reconforge.consolidation_impairment_artifacts DROP CONSTRAINT IF EXISTS consolidation_impairment_tenant_legal_entity_fkey")
    op.execute("ALTER TABLE reconforge.consolidation_impairment_artifacts DROP CONSTRAINT IF EXISTS consolidation_impairment_tenant_organization_fkey")
    op.execute("ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DROP CONSTRAINT IF EXISTS consolidation_deferred_tax_tenant_legal_entity_fkey")
    op.execute("ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DROP CONSTRAINT IF EXISTS consolidation_deferred_tax_tenant_organization_fkey")
    op.execute("ALTER TABLE reconforge.consolidation_impairment_artifacts DROP COLUMN IF EXISTS legal_entity_id")
    op.execute("ALTER TABLE reconforge.consolidation_impairment_artifacts DROP COLUMN IF EXISTS organization_id")
    op.execute("ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DROP COLUMN IF EXISTS legal_entity_id")
    op.execute("ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DROP COLUMN IF EXISTS organization_id")
