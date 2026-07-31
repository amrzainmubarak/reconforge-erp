"""Attribute legacy business aggregates to transaction workspace scope."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_workspace_attribution",
    "POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL",
)

revision = "0045_postgres_workspace_scope"
down_revision = "0044_postgres_business_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE reconforge.organizations ALTER COLUMN application_workspace_id DROP DEFAULT")
    op.execute("ALTER TABLE reconforge.fiscal_periods ALTER COLUMN application_workspace_id DROP DEFAULT")
    for table_name in (
        "evidence_links",
        "reconciliation_inputs",
        "reconciliation_results",
        "reconciliation_exceptions",
        "reconciliation_execution_checkpoints",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_scope ON reconforge.{table_name}")
        op.execute(
            f"CREATE POLICY tenant_scope ON reconforge.{table_name} "
            "USING (tenant_id=current_setting('app.tenant_id',true)) "
            "WITH CHECK (tenant_id=current_setting('app.tenant_id',true))"
        )
    for table_name in (
        "ap_idempotency_keys",
        "approval_requests",
        "ar_idempotency_keys",
        "certification_records",
        "evidence_registry",
        "evidence_requirements",
        "reconciliation_runs",
        "remediation_plans",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_scope ON reconforge.{table_name}")
        op.execute(
            f"CREATE POLICY tenant_scope ON reconforge.{table_name} "
            "USING (tenant_id=current_setting('app.tenant_id',true)) "
            "WITH CHECK (tenant_id=current_setting('app.tenant_id',true))"
        )
        op.execute(f"DROP INDEX IF EXISTS reconforge.{table_name}_workspace_scope_idx")
        op.execute(f"ALTER TABLE reconforge.{table_name} DROP COLUMN IF EXISTS workspace_id")
