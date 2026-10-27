"""PostgreSQL performance and secondary indexes: GL lines, entries, audit events, active queues, and ERP v1.0 tables."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0152_pg_performance_indexes"
down_revision = "0151_pg_enterprise_erp_v1_tables"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- 1. Financial GL Lines and Entries Indexes
CREATE INDEX IF NOT EXISTS idx_finance_lines_tenant_account
    ON reconforge.finance_entry_lines (tenant_id, account_id);

CREATE INDEX IF NOT EXISTS idx_finance_entries_tenant_date
    ON reconforge.finance_entries (tenant_id, posting_date, entry_number);

-- 2. Domain Audit Events Indexes
CREATE INDEX IF NOT EXISTS idx_domain_audit_events_object
    ON reconforge.domain_audit_events (tenant_id, object_type, object_id, sequence);

CREATE INDEX IF NOT EXISTS idx_domain_audit_events_created
    ON reconforge.domain_audit_events (tenant_id, created_at, id);

-- 3. Partial Indexes for Active Queues
CREATE INDEX IF NOT EXISTS idx_durable_jobs_active_queue
    ON reconforge.durable_jobs (tenant_id, status, created_at, id)
    WHERE status IN ('queued', 'running', 'retrying');

CREATE INDEX IF NOT EXISTS idx_outbox_events_unprocessed
    ON reconforge.outbox_events (tenant_id, available_at, created_at)
    WHERE status IN ('Pending', 'Claimed');

-- 4. ERP v1.0 Secondary Indexes (Migration 0151 Tables)
CREATE INDEX IF NOT EXISTS idx_shop_floor_lots_item_status
    ON reconforge.shop_floor_lots (tenant_id, workspace_id, item_id, status);

CREATE INDEX IF NOT EXISTS idx_shop_floor_genealogy_child
    ON reconforge.shop_floor_lot_genealogy (tenant_id, workspace_id, child_lot_id, parent_lot_id);

CREATE INDEX IF NOT EXISTS idx_shop_floor_dispatches_wo
    ON reconforge.shop_floor_dispatches (tenant_id, workspace_id, work_order_id);

CREATE INDEX IF NOT EXISTS idx_shop_floor_steps_wo_seq
    ON reconforge.shop_floor_steps (tenant_id, workspace_id, work_order_id, operation_sequence);

CREATE INDEX IF NOT EXISTS idx_shop_floor_steps_wc_status
    ON reconforge.shop_floor_steps (tenant_id, workspace_id, work_center_id, status);

CREATE INDEX IF NOT EXISTS idx_project_wbs_tasks_project_status
    ON reconforge.project_wbs_tasks (tenant_id, workspace_id, project_id, status);

CREATE INDEX IF NOT EXISTS idx_project_milestones_project_status
    ON reconforge.project_milestones (tenant_id, workspace_id, project_id, status);

CREATE INDEX IF NOT EXISTS idx_project_time_logs_task_date
    ON reconforge.project_time_logs (tenant_id, workspace_id, project_id, task_id, log_date);

CREATE INDEX IF NOT EXISTS idx_mps_requisitions_plan_item
    ON reconforge.mps_sourcing_requisitions (tenant_id, workspace_id, plan_id, item_id, status);

CREATE INDEX IF NOT EXISTS idx_intercompany_pis_rules_entities
    ON reconforge.intercompany_profit_in_stock_rules (tenant_id, workspace_id, selling_entity, buying_entity);
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS reconforge.idx_intercompany_pis_rules_entities;
DROP INDEX IF EXISTS reconforge.idx_mps_requisitions_plan_item;
DROP INDEX IF EXISTS reconforge.idx_project_time_logs_task_date;
DROP INDEX IF EXISTS reconforge.idx_project_milestones_project_status;
DROP INDEX IF EXISTS reconforge.idx_project_wbs_tasks_project_status;
DROP INDEX IF EXISTS reconforge.idx_shop_floor_steps_wc_status;
DROP INDEX IF EXISTS reconforge.idx_shop_floor_steps_wo_seq;
DROP INDEX IF EXISTS reconforge.idx_shop_floor_dispatches_wo;
DROP INDEX IF EXISTS reconforge.idx_shop_floor_genealogy_child;
DROP INDEX IF EXISTS reconforge.idx_shop_floor_lots_item_status;
DROP INDEX IF EXISTS reconforge.idx_outbox_events_unprocessed;
DROP INDEX IF EXISTS reconforge.idx_durable_jobs_active_queue;
DROP INDEX IF EXISTS reconforge.idx_domain_audit_events_created;
DROP INDEX IF EXISTS reconforge.idx_domain_audit_events_object;
DROP INDEX IF EXISTS reconforge.idx_finance_entries_tenant_date;
DROP INDEX IF EXISTS reconforge.idx_finance_lines_tenant_account;
"""


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
