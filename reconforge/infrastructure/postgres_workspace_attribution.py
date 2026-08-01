"""Backward-compatible workspace attribution for legacy business aggregates."""

from __future__ import annotations

from typing import Any

POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL = r"""
ALTER TABLE reconforge.organizations
 ALTER COLUMN application_workspace_id
 SET DEFAULT NULLIF(current_setting('app.workspace_id',true),'');
ALTER TABLE reconforge.fiscal_periods
 ALTER COLUMN application_workspace_id
 SET DEFAULT NULLIF(current_setting('app.workspace_id',true),'');

DO $reconforge$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'ap_idempotency_keys','approval_requests','ar_idempotency_keys',
    'certification_records','evidence_registry','evidence_requirements',
    'reconciliation_runs','remediation_plans'
  ] LOOP
    EXECUTE format(
      'ALTER TABLE reconforge.%1$I ADD COLUMN IF NOT EXISTS workspace_id TEXT '
      'DEFAULT NULLIF(current_setting(''app.workspace_id'',true),'''')', table_name
    );
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
       WHERE conname = table_name || '_tenant_workspace_fkey'
         AND conrelid = format('reconforge.%I', table_name)::regclass
    ) THEN
      EXECUTE format(
        'ALTER TABLE reconforge.%1$I ADD CONSTRAINT %2$I '
        'FOREIGN KEY (tenant_id,workspace_id) '
        'REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE RESTRICT',
        table_name, table_name || '_tenant_workspace_fkey'
      );
    END IF;
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %2$I ON reconforge.%1$I(tenant_id,workspace_id)',
      table_name, table_name || '_workspace_scope_idx'
    );
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I '
      'USING (tenant_id=current_setting(''app.tenant_id'',true) AND '
      '(NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL OR '
      'workspace_id=current_setting(''app.workspace_id'',true))) '
      'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) AND '
      '(NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL OR '
      'workspace_id=current_setting(''app.workspace_id'',true)))', table_name
    );
  END LOOP;
END $reconforge$;

DO $reconforge$
DECLARE target RECORD;
DECLARE predicate TEXT;
BEGIN
  FOR target IN
    SELECT * FROM (VALUES
      ('evidence_links','evidence_registry','evidence_id','id'),
      ('reconciliation_inputs','reconciliation_runs','run_id','id'),
      ('reconciliation_results','reconciliation_runs','run_id','id'),
      ('reconciliation_exceptions','reconciliation_runs','run_id','id'),
      ('reconciliation_execution_checkpoints','reconciliation_runs','run_id','id')
    ) AS relationships(child_table,parent_table,child_key,parent_key)
  LOOP
    predicate := format(
      'tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.%1$I parent WHERE parent.tenant_id=%2$I.tenant_id '
      'AND parent.%3$I=%2$I.%4$I)',
      target.parent_table, target.child_table, target.parent_key, target.child_key
    );
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', target.child_table);
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', target.child_table);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I USING (%2$s) WITH CHECK (%2$s)',
      target.child_table, predicate
    );
  END LOOP;
END $reconforge$;
"""


def install_postgres_workspace_attribution_schema(connection: Any) -> None:
    """Install workspace attribution and policies without rewriting legacy rows."""

    connection.execute(POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL)
