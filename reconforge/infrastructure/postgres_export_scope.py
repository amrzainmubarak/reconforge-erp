"""Workspace RLS policies required by hierarchical Evidence exports."""

from __future__ import annotations

from typing import Any

POSTGRES_EXPORT_SCOPE_SCHEMA_SQL = r"""
DO $reconforge$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'evidence_application_registry','evidence_application_links',
    'evidence_application_requirements'
  ] LOOP
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I '
      'USING (tenant_id=current_setting(''app.tenant_id'',true) '
      'AND (NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL '
      'OR workspace_id=current_setting(''app.workspace_id'',true))) '
      'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) '
      'AND (NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL '
      'OR workspace_id=current_setting(''app.workspace_id'',true)))',
      table_name
    );
  END LOOP;
END $reconforge$;

DROP POLICY IF EXISTS tenant_scope ON reconforge.legal_entities;
CREATE POLICY tenant_scope ON reconforge.legal_entities
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR EXISTS (
        SELECT 1 FROM reconforge.organizations parent
        WHERE parent.tenant_id=legal_entities.tenant_id
          AND parent.id=legal_entities.organization_id
          AND parent.application_workspace_id=current_setting('app.workspace_id',true)))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR EXISTS (
        SELECT 1 FROM reconforge.organizations parent
        WHERE parent.tenant_id=legal_entities.tenant_id
          AND parent.id=legal_entities.organization_id
          AND parent.application_workspace_id=current_setting('app.workspace_id',true)))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR id=current_setting('app.legal_entity_id',true)));

DROP POLICY IF EXISTS tenant_scope ON reconforge.branches;
CREATE POLICY tenant_scope ON reconforge.branches
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR EXISTS (
        SELECT 1 FROM reconforge.organizations parent
        WHERE parent.tenant_id=branches.tenant_id
          AND parent.id=branches.organization_id
          AND parent.application_workspace_id=current_setting('app.workspace_id',true)))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL
        OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR EXISTS (
        SELECT 1 FROM reconforge.organizations parent
        WHERE parent.tenant_id=branches.tenant_id
          AND parent.id=branches.organization_id
          AND parent.application_workspace_id=current_setting('app.workspace_id',true)))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
        OR legal_entity_id=current_setting('app.legal_entity_id',true)));
"""


def install_postgres_export_scope_schema(connection: Any) -> None:
    """Install workspace-aware policies for Evidence export sources."""

    connection.execute(POSTGRES_EXPORT_SCOPE_SCHEMA_SQL)
