"""Compose direct business scope columns into PostgreSQL RLS policies."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_business_scope",
    "POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL",
)

revision = "0044_postgres_business_scope"
down_revision = "0043_postgres_export_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    # Restore the pre-0044 tenant-only baseline. Purpose-built hierarchy policies
    # were excluded from the upgrade and are deliberately left untouched.
    op.execute(
        """
        DO $reconforge$
        DECLARE target RECORD;
        BEGIN
          FOR target IN
            SELECT c.table_name
              FROM information_schema.columns c
             WHERE c.table_schema='reconforge'
               AND c.table_name NOT IN (
                 'branches','domain_periods','domain_workspaces','durable_jobs',
                 'legal_entities','master_data_workspace_organizations','organizations'
               )
             GROUP BY c.table_name
            HAVING bool_or(c.column_name='tenant_id')
               AND bool_or(c.column_name IN (
                 'workspace_id','application_workspace_id','organization_id',
                 'legal_entity_id','entity_id','branch_id'
               ))
          LOOP
            EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', target.table_name);
            EXECUTE format(
              'CREATE POLICY tenant_isolation ON reconforge.%1$I '
              'USING (tenant_id=current_setting(''app.tenant_id'',true)) '
              'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',
              target.table_name
            );
          END LOOP;
        END $reconforge$;
        """
    )
    op.execute(
        """
        DO $reconforge$
        DECLARE table_name TEXT;
        BEGIN
          FOREACH table_name IN ARRAY ARRAY[
            'account_reconciliation_items','account_reconciliation_transitions',
            'ap_goods_receipt_lines','ap_purchase_order_lines','ap_supplier_invoice_lines',
            'ar_invoice_lines','close_application_dependencies','close_application_tasks',
            'close_task_dependencies','close_tasks','control_test_results',
            'exception_queue_history','finance_entry_lines','finance_entry_line_dimensions',
            'inventory_count_lines','inventory_locations','inventory_movement_lines',
            'inventory_valuation_input_costs','inventory_valuation_lines',
            'inventory_valuation_reversal_effects','ledger_lines'
          ] LOOP
            EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', table_name);
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
            EXECUTE format(
              'CREATE POLICY tenant_isolation ON reconforge.%1$I '
              'USING (tenant_id=current_setting(''app.tenant_id'',true)) '
              'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',
              table_name
            );
          END LOOP;
        END $reconforge$;
        """
    )
