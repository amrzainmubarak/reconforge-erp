"""PostgreSQL RLS policies for explicit workspace and entity execution scope."""

from __future__ import annotations

from typing import Any

POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL = r"""
DROP POLICY IF EXISTS tenant_scope ON reconforge.domain_workspaces;
CREATE POLICY tenant_scope ON reconforge.domain_workspaces
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR id=current_setting('app.workspace_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR id=current_setting('app.workspace_id',true)));

DROP POLICY IF EXISTS tenant_scope ON reconforge.domain_periods;
CREATE POLICY tenant_scope ON reconforge.domain_periods
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true)));

DROP POLICY IF EXISTS tenant_scope ON reconforge.master_data_workspace_organizations;
CREATE POLICY tenant_scope ON reconforge.master_data_workspace_organizations
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true)));

DROP POLICY IF EXISTS tenant_scope ON reconforge.organizations;
CREATE POLICY tenant_scope ON reconforge.organizations
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR application_workspace_id=current_setting('app.workspace_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR application_workspace_id=current_setting('app.workspace_id',true)));

DROP POLICY IF EXISTS tenant_scope ON reconforge.legal_entities;
CREATE POLICY tenant_scope ON reconforge.legal_entities
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR id=current_setting('app.legal_entity_id',true)));

DROP POLICY IF EXISTS tenant_scope ON reconforge.branches;
CREATE POLICY tenant_scope ON reconforge.branches
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR legal_entity_id=current_setting('app.legal_entity_id',true)));
"""


def install_postgres_execution_scope_schema(connection: Any) -> None:
    """Install the explicit hierarchical RLS policies."""

    connection.execute(POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL)
