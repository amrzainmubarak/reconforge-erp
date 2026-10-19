"""Migration 57: Enterprise ERP v1.0 local tables for SQLite.

Includes:
- Shop floor execution and lot genealogy
- Project WBS, rate cards, milestone billing and time logs
- MPS planning and sourcing requisitions
- Multi-entity consolidated statements
- Intercompany profit-in-stock eliminations
"""

from __future__ import annotations

SQLITE_ENTERPRISE_ERP_V1_SQL = """
CREATE TABLE IF NOT EXISTS shop_floor_lots (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    batch_number TEXT NOT NULL,
    quantity_scaled INTEGER NOT NULL,
    scale_factor INTEGER NOT NULL DEFAULT 1000,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, lot_id)
);

CREATE TABLE IF NOT EXISTS shop_floor_lot_genealogy (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    parent_lot_id TEXT NOT NULL,
    child_lot_id TEXT NOT NULL,
    quantity_consumed_scaled INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, parent_lot_id, child_lot_id)
);

CREATE TABLE IF NOT EXISTS shop_floor_dispatches (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    scheduled_quantity_scaled INTEGER NOT NULL,
    dispatched_lot_id TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, dispatch_id)
);

CREATE TABLE IF NOT EXISTS shop_floor_steps (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    work_center_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_run_minutes INTEGER NOT NULL,
    quantity_completed_scaled INTEGER NOT NULL,
    quantity_scrapped_scaled INTEGER NOT NULL,
    scrap_reason_code TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, step_id)
);

CREATE TABLE IF NOT EXISTS project_wbs_tasks (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_task_id TEXT,
    planned_hours INTEGER NOT NULL DEFAULT 0,
    budget_cost_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, task_id)
);

CREATE TABLE IF NOT EXISTS project_resource_rate_cards (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    rate_card_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hourly_cost_rate_minor INTEGER NOT NULL,
    hourly_bill_rate_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, project_id, resource_role)
);

CREATE TABLE IF NOT EXISTS project_milestones (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    contract_line_id TEXT NOT NULL,
    title TEXT NOT NULL,
    milestone_amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_by TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, milestone_id)
);

CREATE TABLE IF NOT EXISTS project_milestone_invoices (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    customer_code TEXT NOT NULL,
    billed_amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    gl_debit_account TEXT NOT NULL,
    gl_credit_account TEXT NOT NULL,
    finance_entry_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS project_time_logs (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL,
    log_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hours_worked INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    actual_cost_minor INTEGER NOT NULL,
    billable_amount_minor INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, workspace_id, log_id)
);

CREATE TABLE IF NOT EXISTS mps_plans (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    unit_of_measure TEXT NOT NULL,
    quantity_scale INTEGER NOT NULL,
    safety_stock_scaled INTEGER NOT NULL,
    lot_size_multiple_scaled INTEGER NOT NULL,
    opening_inventory_scaled INTEGER NOT NULL,
    plan_digest TEXT NOT NULL,
    plan_payload TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, plan_id, revision)
);

CREATE TABLE IF NOT EXISTS mps_sourcing_requisitions (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    requisition_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    bucket_index INTEGER NOT NULL,
    required_date TEXT NOT NULL,
    shortage_quantity_scaled INTEGER NOT NULL,
    order_quantity_scaled INTEGER NOT NULL,
    preferred_supplier_id TEXT NOT NULL,
    unit_price_ceiling_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    requisition_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'APPROVED',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, requisition_id)
);

CREATE TABLE IF NOT EXISTS consolidated_statement_runs (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    period_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    report_digest TEXT NOT NULL,
    statements_payload TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, report_digest)
);

CREATE TABLE IF NOT EXISTS intercompany_elimination_artifacts (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    version TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    request_payload TEXT NOT NULL,
    result_payload TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, result_digest)
);

CREATE TABLE IF NOT EXISTS intercompany_profit_in_stock_rules (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    selling_entity TEXT NOT NULL,
    buying_entity TEXT NOT NULL,
    inventory_item_code TEXT NOT NULL,
    margin_basis_points INTEGER NOT NULL,
    ending_inventory_cost_minor INTEGER NOT NULL,
    nci_share_basis_points INTEGER NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, rule_id)
);

CREATE TABLE IF NOT EXISTS intercompany_profit_in_stock_eliminations (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    elimination_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    unrealized_profit_minor INTEGER NOT NULL,
    parent_share_minor INTEGER NOT NULL,
    nci_share_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    debit_account TEXT NOT NULL,
    credit_account TEXT NOT NULL,
    rationale TEXT NOT NULL,
    finance_entry_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, elimination_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_floor_lots_ws_lot ON shop_floor_lots (workspace_id, lot_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_floor_lot_genealogy_ws_pair ON shop_floor_lot_genealogy (workspace_id, parent_lot_id, child_lot_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_floor_dispatches_ws_disp ON shop_floor_dispatches (workspace_id, dispatch_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_floor_steps_ws_step ON shop_floor_steps (workspace_id, step_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_wbs_tasks_ws_task ON project_wbs_tasks (workspace_id, task_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_rate_cards_ws_role ON project_resource_rate_cards (workspace_id, project_id, resource_role);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_milestones_ws_ms ON project_milestones (workspace_id, milestone_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_invoices_ws_inv ON project_milestone_invoices (workspace_id, invoice_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_time_logs_ws_log ON project_time_logs (workspace_id, log_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mps_plans_ws_rev ON mps_plans (workspace_id, plan_id, revision);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mps_sourcing_req_ws_req ON mps_sourcing_requisitions (workspace_id, requisition_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_csr_ws_digest ON consolidated_statement_runs (workspace_id, report_digest);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ice_artifacts_ws_digest ON intercompany_elimination_artifacts (workspace_id, result_digest);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ice_rules_ws_rule ON intercompany_profit_in_stock_rules (workspace_id, rule_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ice_elims_ws_elim ON intercompany_profit_in_stock_eliminations (workspace_id, elimination_id);
"""
