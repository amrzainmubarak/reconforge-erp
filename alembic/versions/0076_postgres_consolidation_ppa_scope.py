"""Add hierarchy attribution to PostgreSQL PPA evidence."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_consolidation_ppa_scope",
    "POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL",
)

revision = "0076_pg_consolidation_ppa_scope"
down_revision = "0075_pg_job_organization_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM reconforge.consolidation_ppa_artifacts
            WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'refusing to discard consolidation PPA hierarchy attribution';
          END IF;
        END $reconforge$;
        """
    )
    op.execute("DROP INDEX IF EXISTS reconforge.consolidation_ppa_hierarchy_scope_idx")
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_ppa_artifacts")
    op.execute(
        """
        CREATE POLICY tenant_scope ON reconforge.consolidation_ppa_artifacts
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )
    op.execute(
        "ALTER TABLE reconforge.consolidation_ppa_artifacts "
        "DROP CONSTRAINT IF EXISTS consolidation_ppa_scope_result_digest_key"
    )
    op.execute(
        "ALTER TABLE reconforge.consolidation_ppa_artifacts "
        "ADD CONSTRAINT consolidation_ppa_artifacts_tenant_id_result_digest_key "
        "UNIQUE (tenant_id, result_digest)"
    )
    op.execute(
        "ALTER TABLE reconforge.consolidation_ppa_artifacts "
        "DROP CONSTRAINT IF EXISTS consolidation_ppa_tenant_legal_entity_fkey"
    )
    op.execute(
        "ALTER TABLE reconforge.consolidation_ppa_artifacts "
        "DROP CONSTRAINT IF EXISTS consolidation_ppa_tenant_organization_fkey"
    )
    op.execute("ALTER TABLE reconforge.consolidation_ppa_artifacts DROP COLUMN IF EXISTS legal_entity_id")
    op.execute("ALTER TABLE reconforge.consolidation_ppa_artifacts DROP COLUMN IF EXISTS organization_id")
