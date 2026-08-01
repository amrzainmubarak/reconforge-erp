"""Bind Evidence export sources to workspace RLS scope."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_EXPORT_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_export_scope", "POSTGRES_EXPORT_SCOPE_SCHEMA_SQL"
)

revision = "0043_postgres_export_scope"
down_revision = "0042_postgres_job_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_EXPORT_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    for table_name in (
        "evidence_application_registry",
        "evidence_application_links",
        "evidence_application_requirements",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_scope ON reconforge.{table_name}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON reconforge.{table_name}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON reconforge.{table_name} "
            "USING (tenant_id=current_setting('app.tenant_id',true)) "
            "WITH CHECK (tenant_id=current_setting('app.tenant_id',true))"
        )
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.legal_entities")
    op.execute(
        "CREATE POLICY tenant_scope ON reconforge.legal_entities "
        "USING (tenant_id=current_setting('app.tenant_id',true) "
        "AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL "
        "OR organization_id=current_setting('app.organization_id',true)) "
        "AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL "
        "OR id=current_setting('app.legal_entity_id',true))) "
        "WITH CHECK (tenant_id=current_setting('app.tenant_id',true) "
        "AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL "
        "OR organization_id=current_setting('app.organization_id',true)) "
        "AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL "
        "OR id=current_setting('app.legal_entity_id',true)))"
    )
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.branches")
    op.execute(
        "CREATE POLICY tenant_scope ON reconforge.branches "
        "USING (tenant_id=current_setting('app.tenant_id',true) "
        "AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL "
        "OR organization_id=current_setting('app.organization_id',true)) "
        "AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL "
        "OR legal_entity_id=current_setting('app.legal_entity_id',true))) "
        "WITH CHECK (tenant_id=current_setting('app.tenant_id',true) "
        "AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL "
        "OR organization_id=current_setting('app.organization_id',true)) "
        "AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL "
        "OR legal_entity_id=current_setting('app.legal_entity_id',true)))"
    )
