"""Bind durable jobs and worker evidence to workspace/entity RLS scope."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_JOB_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_job_scope", "POSTGRES_JOB_SCOPE_SCHEMA_SQL"
)

revision = "0042_postgres_job_scope"
down_revision = "0041_postgres_execution_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_JOB_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    for table_name in (
        "durable_jobs", "durable_job_transitions", "durable_job_leases",
        "durable_job_lease_events", "durable_job_partition_effects",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_scope ON reconforge.{table_name}")
        op.execute(
            f"CREATE POLICY tenant_scope ON reconforge.{table_name} "
            "USING (tenant_id=current_setting('app.tenant_id',true)) "
            "WITH CHECK (tenant_id=current_setting('app.tenant_id',true))"
        )
