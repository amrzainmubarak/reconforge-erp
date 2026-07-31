"""Composable PostgreSQL RLS for business tables with direct scope columns."""

from __future__ import annotations

from typing import Any

# Hierarchy roots and durable jobs have purpose-built policies that resolve IDs
# through their authoritative parents. Every other tenant table carrying one or
# more direct business-scope columns is tightened by this migration.
POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL = r"""
DO $reconforge$
DECLARE
  target RECORD;
  predicate TEXT;
BEGIN
  FOR target IN
    SELECT c.table_name,
           bool_or(c.column_name = 'workspace_id') AS has_workspace,
           bool_or(c.column_name = 'application_workspace_id') AS has_application_workspace,
           bool_or(c.column_name = 'organization_id') AS has_organization,
           bool_or(c.column_name = 'legal_entity_id') AS has_legal_entity,
           bool_or(c.column_name = 'entity_id') AS has_entity,
           bool_or(c.column_name = 'branch_id') AS has_branch
      FROM information_schema.columns c
     WHERE c.table_schema = 'reconforge'
       AND c.table_name NOT IN (
         'branches', 'domain_periods', 'domain_workspaces', 'durable_jobs',
         'legal_entities', 'master_data_workspace_organizations', 'organizations'
       )
     GROUP BY c.table_name
    HAVING bool_or(c.column_name = 'tenant_id')
       AND bool_or(c.column_name IN (
         'workspace_id', 'application_workspace_id', 'organization_id',
         'legal_entity_id', 'entity_id', 'branch_id'
       ))
  LOOP
    predicate := 'tenant_id=current_setting(''app.tenant_id'',true)';
    IF target.has_workspace THEN
      predicate := predicate || ' AND (NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL OR workspace_id=current_setting(''app.workspace_id'',true))';
    END IF;
    IF target.has_application_workspace THEN
      predicate := predicate || ' AND (NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL OR application_workspace_id=current_setting(''app.workspace_id'',true))';
    END IF;
    IF target.has_organization THEN
      predicate := predicate || ' AND (NULLIF(current_setting(''app.organization_id'',true),'''') IS NULL OR organization_id=current_setting(''app.organization_id'',true))';
    END IF;
    IF target.has_legal_entity THEN
      predicate := predicate || ' AND (NULLIF(current_setting(''app.legal_entity_id'',true),'''') IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true))';
    END IF;
    IF target.has_entity THEN
      predicate := predicate || ' AND (NULLIF(current_setting(''app.entity_id'',true),'''') IS NULL OR entity_id=current_setting(''app.entity_id'',true))';
    END IF;
    IF target.has_branch THEN
      predicate := predicate || ' AND (NULLIF(current_setting(''app.branch_id'',true),'''') IS NULL OR branch_id=current_setting(''app.branch_id'',true))';
    END IF;

    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', target.table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', target.table_name);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I USING (%2$s) WITH CHECK (%2$s)',
      target.table_name, predicate
    );
  END LOOP;
END $reconforge$;

DO $reconforge$
DECLARE target RECORD;
DECLARE predicate TEXT;
BEGIN
  FOR target IN
    SELECT * FROM (VALUES
      ('account_reconciliation_items','account_reconciliation_records','reconciliation_id','id'),
      ('account_reconciliation_transitions','account_reconciliation_records','reconciliation_id','id'),
      ('ap_goods_receipt_lines','ap_goods_receipts','receipt_id','id'),
      ('ap_purchase_order_lines','ap_purchase_orders','purchase_order_id','id'),
      ('ap_supplier_invoice_lines','ap_supplier_invoices','supplier_invoice_id','id'),
      ('ar_invoice_lines','ar_invoices','invoice_id','id'),
      ('close_application_dependencies','close_application_periods','close_period_id','id'),
      ('close_application_tasks','close_application_periods','close_period_id','id'),
      ('close_task_dependencies','close_periods','close_period_id','id'),
      ('close_tasks','close_periods','close_period_id','id'),
      ('control_test_results','control_test_plans','test_plan_id','id'),
      ('exception_queue_history','exception_queue_records','exception_id','id'),
      ('finance_entry_lines','finance_entries','entry_id','id'),
      ('finance_entry_line_dimensions','finance_entry_lines','entry_line_id','id'),
      ('inventory_count_lines','inventory_count_sessions','session_id','id'),
      ('inventory_locations','inventory_warehouses','warehouse_id','id'),
      ('inventory_movement_lines','inventory_movements','movement_id','id'),
      ('inventory_valuation_input_costs','inventory_valuation_documents','valuation_document_id','id'),
      ('inventory_valuation_lines','inventory_valuation_documents','valuation_document_id','id'),
      ('inventory_valuation_reversal_effects','inventory_valuation_reversals','reversal_id','id'),
      ('ledger_lines','ledger_entries','entry_id','id')
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


def install_postgres_business_scope_schema(connection: Any) -> None:
    """Tighten every direct-scope business table present in the schema."""

    connection.execute(POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL)
