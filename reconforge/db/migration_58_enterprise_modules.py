"""Migration58 registers previously runtime-created Community module tables."""

SQLITE_ENTERPRISE_MODULES_SQL = r"""
CREATE TABLE IF NOT EXISTS hcm_employee_identities (
    workspace_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (workspace_id, employee_id)
);

CREATE TABLE IF NOT EXISTS hcm_leave_entitlement_balances (
    workspace_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    annual_entitlement_days INTEGER NOT NULL,
    accrued_days INTEGER NOT NULL,
    consumed_days INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, employee_id, leave_type)
);

CREATE TABLE IF NOT EXISTS hcm_leave_requests (
    workspace_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_user_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    requested_days INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    approved_by_user_id TEXT,
    rejection_reason TEXT,
    PRIMARY KEY (workspace_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_hcm_leave_requests_employee
ON hcm_leave_requests (workspace_id, employee_id);

CREATE TABLE IF NOT EXISTS crm_opportunities (
    workspace_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL,
    estimated_close_date TEXT NOT NULL,
    currency TEXT NOT NULL,
    projected_amount_minor INTEGER NOT NULL,
    win_probability_bps INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS crm_quotations (
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    submitter_user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_by_user_id TEXT,
    approval_role TEXT,
    PRIMARY KEY (workspace_id, quote_id)
);

CREATE TABLE IF NOT EXISTS crm_quotation_lines (
    quote_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_minor INTEGER NOT NULL,
    discount_bps INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (quote_id, line_number)
);

CREATE TABLE IF NOT EXISTS crm_contracts (
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    billing_frequency TEXT NOT NULL,
    total_contract_value_minor INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (workspace_id, contract_id)
);

CREATE TABLE IF NOT EXISTS crm_subscription_plans (
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    billing_interval TEXT NOT NULL,
    unit_price_minor INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, plan_id)
);

CREATE TABLE IF NOT EXISTS crm_subscriptions (
    workspace_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_start TEXT NOT NULL,
    current_period_end TEXT NOT NULL,
    auto_renew INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (workspace_id, subscription_id)
);

CREATE TABLE IF NOT EXISTS workcenter_calendars (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    name TEXT NOT NULL,
    daily_capacity_minutes INTEGER NOT NULL,
    blackout_dates TEXT NOT NULL,
    fixed_asset_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, workcenter_id)
);

CREATE TABLE IF NOT EXISTS workcenter_shifts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    name TEXT NOT NULL,
    start_minute INTEGER NOT NULL,
    end_minute INTEGER NOT NULL,
    break_minutes INTEGER NOT NULL,
    days_of_week TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, workcenter_id, shift_id)
);

CREATE TABLE IF NOT EXISTS capacity_slot_reservations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    scheduled_date TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_minute INTEGER,
    end_minute INTEGER,
    shift_id TEXT,
    status TEXT NOT NULL DEFAULT 'BOOKED',
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, reservation_id)
);

CREATE INDEX IF NOT EXISTS idx_capacity_slots_lookup
ON capacity_slot_reservations (workspace_id, workcenter_id, scheduled_date, status);

CREATE TABLE IF NOT EXISTS manufacturing_boms (
    bom_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    base_quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (item_id, revision)
);

CREATE TABLE IF NOT EXISTS manufacturing_bom_components (
    bom_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    component_item_id TEXT NOT NULL,
    component_name TEXT NOT NULL,
    component_type TEXT NOT NULL,
    quantity_per_parent INTEGER NOT NULL,
    scrap_factor_bps INTEGER NOT NULL DEFAULT 0,
    substitute_item_id TEXT,
    substitute_ratio_bps INTEGER NOT NULL DEFAULT 10000,
    PRIMARY KEY (bom_id, line_number)
);

CREATE INDEX IF NOT EXISTS idx_bom_components_parent
ON manufacturing_bom_components (bom_id);

CREATE TABLE IF NOT EXISTS treasury_cash_positions (
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    bank_account_id TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    cleared_balance_minor INTEGER NOT NULL,
    minimum_covenant_minor INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (workspace_id, legal_entity_id, bank_account_id)
);

CREATE TABLE IF NOT EXISTS treasury_liquidity_flows (
    flow_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    confidence_bps INTEGER NOT NULL DEFAULT 10000,
    status TEXT NOT NULL DEFAULT 'projected',
    PRIMARY KEY (workspace_id, flow_id)
);

CREATE INDEX IF NOT EXISTS idx_treasury_flows_due
ON treasury_liquidity_flows (workspace_id, legal_entity_id, currency, due_date);

CREATE TABLE IF NOT EXISTS quality_inspection_plans (
    plan_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    name TEXT NOT NULL,
    sample_size_units INTEGER NOT NULL,
    specifications_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, item_id, revision)
);

CREATE TABLE IF NOT EXISTS quality_ncrs (
    ncr_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    defect_code TEXT NOT NULL,
    defect_severity TEXT NOT NULL,
    inspector_id TEXT NOT NULL,
    quarantined_quantity_scaled INTEGER NOT NULL,
    status TEXT NOT NULL,
    disposition TEXT,
    disposition_notes TEXT,
    disposition_by TEXT,
    disposition_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_rework_orders (
    rework_order_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_work_order_id TEXT NOT NULL,
    ncr_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    rework_quantity_scaled INTEGER NOT NULL,
    rework_routing_steps_json TEXT NOT NULL,
    rework_cost_center TEXT NOT NULL,
    status TEXT NOT NULL,
    accumulated_rework_cost_minor INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""
