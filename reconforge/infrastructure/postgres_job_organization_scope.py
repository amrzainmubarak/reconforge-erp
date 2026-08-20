"""Add organization attribution and RLS to PostgreSQL durable jobs."""

from __future__ import annotations

from typing import Any

POSTGRES_JOB_ORGANIZATION_SCOPE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.durable_jobs
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.durable_jobs
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
CREATE INDEX IF NOT EXISTS durable_jobs_org_scope_status_idx
    ON reconforge.durable_jobs(tenant_id, organization_id, workspace_id, status, created_at, id);

DROP POLICY IF EXISTS tenant_scope ON reconforge.durable_jobs;
CREATE POLICY tenant_scope ON reconforge.durable_jobs
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL
        OR entity_id=current_setting('app.entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL
        OR entity_id=current_setting('app.entity_id',true)));
"""


def install_postgres_job_organization_scope_schema(connection: Any) -> None:
    """Install the additive organization scope for durable jobs."""

    connection.execute(POSTGRES_JOB_ORGANIZATION_SCOPE_SCHEMA_SQL)
