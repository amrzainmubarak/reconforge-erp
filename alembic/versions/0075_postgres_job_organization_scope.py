"""Add organization attribution to durable PostgreSQL jobs."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_JOB_ORGANIZATION_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_job_organization_scope",
    "POSTGRES_JOB_ORGANIZATION_SCOPE_SCHEMA_SQL",
)

revision = "0075_pg_job_organization_scope"
down_revision = "0074_pg_outbox_consumer_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_JOB_ORGANIZATION_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS reconforge.durable_jobs_org_scope_status_idx")
    op.execute("DROP POLICY IF EXISTS tenant_scope ON reconforge.durable_jobs")
    op.execute(
        "CREATE POLICY tenant_scope ON reconforge.durable_jobs "
        "USING (tenant_id=current_setting('app.tenant_id',true) "
        "AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL "
        "OR workspace_id=current_setting('app.workspace_id',true)) "
        "AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL "
        "OR entity_id=current_setting('app.entity_id',true))) "
        "WITH CHECK (tenant_id=current_setting('app.tenant_id',true) "
        "AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL "
        "OR workspace_id=current_setting('app.workspace_id',true)) "
        "AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL "
        "OR entity_id=current_setting('app.entity_id',true)))"
    )
    op.execute("ALTER TABLE reconforge.durable_jobs ALTER COLUMN organization_id DROP DEFAULT")
    op.execute("ALTER TABLE reconforge.durable_jobs DROP COLUMN IF EXISTS organization_id")
