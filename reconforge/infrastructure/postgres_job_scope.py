"""Workspace/entity RLS policies for durable background jobs and their evidence."""

from __future__ import annotations

from typing import Any

POSTGRES_JOB_SCOPE_SCHEMA_SQL = r"""
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

DO $reconforge$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'durable_job_transitions','durable_job_leases','durable_job_lease_events',
    'durable_job_partition_effects'
  ] LOOP
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I '
      'USING (tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.durable_jobs parent '
      'WHERE parent.tenant_id=%1$I.tenant_id AND parent.id=%1$I.job_id)) '
      'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.durable_jobs parent '
      'WHERE parent.tenant_id=%1$I.tenant_id AND parent.id=%1$I.job_id))',
      table_name
    );
  END LOOP;
END $reconforge$;
"""


def install_postgres_job_scope_schema(connection: Any) -> None:
    """Install workspace/entity policies for durable jobs and child evidence."""

    connection.execute(POSTGRES_JOB_SCOPE_SCHEMA_SQL)
