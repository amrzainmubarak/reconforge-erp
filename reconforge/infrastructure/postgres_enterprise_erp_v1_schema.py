"""PostgreSQL DDL schema definitions for Enterprise ERP v1.0 tables with FORCE RLS.

Includes:
- Shop Floor Execution & Lot Genealogy
- Project WBS, Rate Cards, Milestone Billing & Time Tracking
- Master Production Scheduling (MPS) & Sourcing Requisitions
- Multi-Entity Consolidated Financial Statements
- Intercompany Profit-in-Stock Eliminations & Artifacts
"""

from __future__ import annotations

from typing import Any

from reconforge.platform.common import PlatformError

UPGRADE_SQL = r"""
-- ============================================================================
-- 1. SHOP FLOOR EXECUTION & LOT GENEALOGY
-- ============================================================================

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_lots (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    batch_number TEXT NOT NULL,
    quantity_scaled BIGINT NOT NULL,
    scale_factor INTEGER NOT NULL DEFAULT 1000,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, lot_id)
);
ALTER TABLE reconforge.shop_floor_lots ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_lots FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_lots;
CREATE POLICY tenant_scope ON reconforge.shop_floor_lots
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_lot_genealogy (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    parent_lot_id TEXT NOT NULL,
    child_lot_id TEXT NOT NULL,
    quantity_consumed_scaled BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, parent_lot_id, child_lot_id)
);
ALTER TABLE reconforge.shop_floor_lot_genealogy ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_lot_genealogy FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_lot_genealogy;
CREATE POLICY tenant_scope ON reconforge.shop_floor_lot_genealogy
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_dispatches (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    scheduled_quantity_scaled BIGINT NOT NULL,
    dispatched_lot_id TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, dispatch_id)
);
ALTER TABLE reconforge.shop_floor_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_dispatches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_dispatches;
CREATE POLICY tenant_scope ON reconforge.shop_floor_dispatches
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_steps (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    work_center_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_run_minutes INTEGER NOT NULL,
    quantity_completed_scaled BIGINT NOT NULL,
    quantity_scrapped_scaled BIGINT NOT NULL,
    scrap_reason_code TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, step_id)
);
ALTER TABLE reconforge.shop_floor_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_steps FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_steps;
CREATE POLICY tenant_scope ON reconforge.shop_floor_steps
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));


-- ============================================================================
-- 2. PROJECT WBS, RATE CARDS, MILESTONE BILLING & TIME LOGS
-- ============================================================================

CREATE TABLE IF NOT EXISTS reconforge.project_wbs_tasks (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_task_id TEXT,
    planned_hours INTEGER NOT NULL DEFAULT 0,
    budget_cost_minor BIGINT NOT NULL DEFAULT 0,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, task_id)
);
ALTER TABLE reconforge.project_wbs_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_wbs_tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_wbs_tasks;
CREATE POLICY tenant_scope ON reconforge.project_wbs_tasks
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_resource_rate_cards (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rate_card_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hourly_cost_rate_minor BIGINT NOT NULL,
    hourly_bill_rate_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, project_id, resource_role)
);
ALTER TABLE reconforge.project_resource_rate_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_resource_rate_cards FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_resource_rate_cards;
CREATE POLICY tenant_scope ON reconforge.project_resource_rate_cards
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_milestones (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    contract_line_id TEXT NOT NULL,
    title TEXT NOT NULL,
    milestone_amount_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_by TEXT,
    verified_at TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, milestone_id)
);
ALTER TABLE reconforge.project_milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_milestones FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_milestones;
CREATE POLICY tenant_scope ON reconforge.project_milestones
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_milestone_invoices (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    customer_code TEXT NOT NULL,
    billed_amount_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    gl_debit_account TEXT NOT NULL,
    gl_credit_account TEXT NOT NULL,
    finance_entry_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, invoice_id)
);
ALTER TABLE reconforge.project_milestone_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_milestone_invoices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_milestone_invoices;
CREATE POLICY tenant_scope ON reconforge.project_milestone_invoices
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_time_logs (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    log_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hours_worked INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    actual_cost_minor BIGINT NOT NULL,
    billable_amount_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, log_id)
);
ALTER TABLE reconforge.project_time_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_time_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_time_logs;
CREATE POLICY tenant_scope ON reconforge.project_time_logs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));


-- ============================================================================
-- 3. MASTER PRODUCTION SCHEDULING (MPS) & SOURCING REQUISITIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS reconforge.mps_plans (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    unit_of_measure TEXT NOT NULL,
    quantity_scale INTEGER NOT NULL,
    safety_stock_scaled BIGINT NOT NULL,
    lot_size_multiple_scaled BIGINT NOT NULL,
    opening_inventory_scaled BIGINT NOT NULL,
    plan_digest TEXT NOT NULL,
    plan_payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, plan_id, revision)
);
ALTER TABLE reconforge.mps_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.mps_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.mps_plans;
CREATE POLICY tenant_scope ON reconforge.mps_plans
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.mps_sourcing_requisitions (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    requisition_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    bucket_index INTEGER NOT NULL,
    required_date DATE NOT NULL,
    shortage_quantity_scaled BIGINT NOT NULL,
    order_quantity_scaled BIGINT NOT NULL,
    preferred_supplier_id TEXT NOT NULL,
    unit_price_ceiling_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    requisition_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'APPROVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, requisition_id)
);
ALTER TABLE reconforge.mps_sourcing_requisitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.mps_sourcing_requisitions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.mps_sourcing_requisitions;
CREATE POLICY tenant_scope ON reconforge.mps_sourcing_requisitions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));


-- ============================================================================
-- 4. MULTI-ENTITY CONSOLIDATED FINANCIAL STATEMENTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS reconforge.consolidated_statement_runs (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    period_id TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    as_of_date DATE NOT NULL,
    report_digest TEXT NOT NULL,
    statements_payload JSONB NOT NULL,
    prepared_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, report_digest)
);
CREATE INDEX IF NOT EXISTS idx_postgres_consolidated_statements_scope
    ON reconforge.consolidated_statement_runs (tenant_id, workspace_id, group_id, period_id);
ALTER TABLE reconforge.consolidated_statement_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidated_statement_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidated_statement_runs;
CREATE POLICY tenant_scope ON reconforge.consolidated_statement_runs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));


-- ============================================================================
-- 5. INTERCOMPANY PROFIT-IN-STOCK ELIMINATION & ARTIFACTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS reconforge.intercompany_elimination_artifacts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^ice-[0-9a-f]{32}$'),
    workspace_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL CHECK (reporting_currency ~ '^[A-Z][A-Z0-9]{2,5}$'),
    version TEXT NOT NULL CHECK (version ~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'),
    request_digest TEXT NOT NULL CHECK (request_digest ~ '^[a-f0-9]{64}$'),
    result_digest TEXT NOT NULL CHECK (result_digest ~ '^[a-f0-9]{64}$'),
    request_payload JSONB NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    result_payload JSONB NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    prepared_by TEXT NOT NULL,
    prepared_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, result_digest)
);
CREATE INDEX IF NOT EXISTS intercompany_elimination_scope_idx
    ON reconforge.intercompany_elimination_artifacts
        (tenant_id, workspace_id, reporting_currency, created_at, id);
ALTER TABLE reconforge.intercompany_elimination_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_elimination_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_elimination_artifacts;
CREATE POLICY tenant_scope ON reconforge.intercompany_elimination_artifacts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.intercompany_profit_in_stock_rules (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    selling_entity TEXT NOT NULL,
    buying_entity TEXT NOT NULL,
    inventory_item_code TEXT NOT NULL,
    margin_basis_points INTEGER NOT NULL,
    ending_inventory_cost_minor BIGINT NOT NULL,
    nci_share_basis_points INTEGER NOT NULL,
    currency TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, rule_id)
);
ALTER TABLE reconforge.intercompany_profit_in_stock_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_profit_in_stock_rules FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_profit_in_stock_rules;
CREATE POLICY tenant_scope ON reconforge.intercompany_profit_in_stock_rules
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.intercompany_profit_in_stock_eliminations (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    elimination_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    unrealized_profit_minor BIGINT NOT NULL,
    parent_share_minor BIGINT NOT NULL,
    nci_share_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    debit_account TEXT NOT NULL,
    credit_account TEXT NOT NULL,
    rationale TEXT NOT NULL,
    finance_entry_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, elimination_id)
);
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_profit_in_stock_eliminations;
CREATE POLICY tenant_scope ON reconforge.intercompany_profit_in_stock_eliminations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""

DOWNGRADE_SQL = r"""
DROP TABLE IF EXISTS reconforge.intercompany_profit_in_stock_eliminations CASCADE;
DROP TABLE IF EXISTS reconforge.intercompany_profit_in_stock_rules CASCADE;
DROP TABLE IF EXISTS reconforge.intercompany_elimination_artifacts CASCADE;

DROP TABLE IF EXISTS reconforge.consolidated_statement_runs CASCADE;

DROP TABLE IF EXISTS reconforge.mps_sourcing_requisitions CASCADE;
DROP TABLE IF EXISTS reconforge.mps_plans CASCADE;

DROP TABLE IF EXISTS reconforge.project_time_logs CASCADE;
DROP TABLE IF EXISTS reconforge.project_milestone_invoices CASCADE;
DROP TABLE IF EXISTS reconforge.project_milestones CASCADE;
DROP TABLE IF EXISTS reconforge.project_resource_rate_cards CASCADE;
DROP TABLE IF EXISTS reconforge.project_wbs_tasks CASCADE;

DROP TABLE IF EXISTS reconforge.shop_floor_steps CASCADE;
DROP TABLE IF EXISTS reconforge.shop_floor_dispatches CASCADE;
DROP TABLE IF EXISTS reconforge.shop_floor_lot_genealogy CASCADE;
DROP TABLE IF EXISTS reconforge.shop_floor_lots CASCADE;
"""


def install_postgres_enterprise_erp_v1_schema(connection: Any) -> None:
    """Execute forward DDL for all enterprise ERP v1.0 tables."""
    try:
        connection.execute(UPGRADE_SQL)
    except Exception as exc:
        raise PlatformError(f"PostgreSQL enterprise ERP v1 schema installation failed: {exc}") from exc
