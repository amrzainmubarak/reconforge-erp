"""Frozen0153 schema: real enterprise module persistence and workspace boundaries.

No application DDL or automatic grants. Populated downgrade is refused.
"""

from __future__ import annotations

REGISTERED_MODULE_TABLES = ('hcm_leave_entitlement_balances', 'hcm_leave_requests', 'crm_opportunities', 'crm_quotations', 'crm_quotation_lines', 'crm_contracts', 'crm_subscription_plans', 'crm_subscriptions', 'workcenter_calendars', 'workcenter_shifts', 'capacity_slot_reservations', 'manufacturing_boms', 'manufacturing_bom_components', 'treasury_cash_positions', 'treasury_liquidity_flows', 'quality_inspection_plans', 'quality_ncrs', 'quality_rework_orders', 'fixed_asset_register_states')
RETAINED_ENTERPRISE_TABLES = ('shop_floor_lots', 'shop_floor_lot_genealogy', 'shop_floor_dispatches', 'shop_floor_steps', 'project_wbs_tasks', 'project_resource_rate_cards', 'project_milestones', 'project_milestone_invoices', 'project_time_logs', 'mps_plans', 'mps_sourcing_requisitions', 'consolidated_statement_runs', 'intercompany_profit_in_stock_rules', 'intercompany_profit_in_stock_eliminations')

UPGRADE_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.hcm_leave_entitlement_balances (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    annual_entitlement_days INTEGER NOT NULL,
    accrued_days INTEGER NOT NULL,
    consumed_days INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, employee_id, leave_type)
);
ALTER TABLE reconforge.hcm_leave_entitlement_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.hcm_leave_entitlement_balances FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_entitlement_balances;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_entitlement_balances
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.hcm_leave_requests (
    tenant_id TEXT NOT NULL,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, request_id)
);
ALTER TABLE reconforge.hcm_leave_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.hcm_leave_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_requests;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_requests
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE INDEX IF NOT EXISTS idx_pg_hcm_leave_requests_employee
ON reconforge.hcm_leave_requests (tenant_id, workspace_id, employee_id);

CREATE TABLE IF NOT EXISTS reconforge.crm_opportunities (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL,
    estimated_close_date TEXT NOT NULL,
    currency TEXT NOT NULL,
    projected_amount_minor BIGINT NOT NULL,
    win_probability_bps INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, opportunity_id)
);
ALTER TABLE reconforge.crm_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_opportunities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_opportunities;
CREATE POLICY tenant_scope ON reconforge.crm_opportunities
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_quotations (
    tenant_id TEXT NOT NULL,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, quote_id)
);
ALTER TABLE reconforge.crm_quotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotations;
CREATE POLICY tenant_scope ON reconforge.crm_quotations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));


CREATE TABLE IF NOT EXISTS reconforge.crm_quotation_lines (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_minor BIGINT NOT NULL,
    discount_bps INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, workspace_id, quote_id, line_number)
);
ALTER TABLE reconforge.crm_quotation_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotation_lines FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotation_lines;
CREATE POLICY tenant_scope ON reconforge.crm_quotation_lines
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_contracts (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    billing_frequency TEXT NOT NULL,
    total_contract_value_minor BIGINT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, contract_id)
);
ALTER TABLE reconforge.crm_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_contracts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_contracts;
CREATE POLICY tenant_scope ON reconforge.crm_contracts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_subscription_plans (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    billing_interval TEXT NOT NULL,
    unit_price_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, plan_id)
);
ALTER TABLE reconforge.crm_subscription_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_subscription_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_subscription_plans;
CREATE POLICY tenant_scope ON reconforge.crm_subscription_plans
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_subscriptions (
    tenant_id TEXT NOT NULL,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, subscription_id)
);
ALTER TABLE reconforge.crm_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_subscriptions;
CREATE POLICY tenant_scope ON reconforge.crm_subscriptions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.workcenter_calendars (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    name TEXT NOT NULL,
    daily_capacity_minutes INTEGER NOT NULL,
    blackout_dates JSONB NOT NULL DEFAULT '[]',
    fixed_asset_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, workcenter_id)
);
ALTER TABLE reconforge.workcenter_calendars ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.workcenter_calendars FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.workcenter_calendars;
CREATE POLICY tenant_scope ON reconforge.workcenter_calendars
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.workcenter_shifts (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    name TEXT NOT NULL,
    start_minute INTEGER NOT NULL,
    end_minute INTEGER NOT NULL,
    break_minutes INTEGER NOT NULL,
    days_of_week JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, workcenter_id, shift_id)
);
ALTER TABLE reconforge.workcenter_shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.workcenter_shifts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.workcenter_shifts;
CREATE POLICY tenant_scope ON reconforge.workcenter_shifts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.capacity_slot_reservations (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    scheduled_date DATE NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_minute INTEGER,
    end_minute INTEGER,
    shift_id TEXT,
    status TEXT NOT NULL DEFAULT 'BOOKED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, reservation_id)
);
ALTER TABLE reconforge.capacity_slot_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.capacity_slot_reservations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.capacity_slot_reservations;
CREATE POLICY tenant_scope ON reconforge.capacity_slot_reservations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.manufacturing_boms (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    bom_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    base_quantity INTEGER NOT NULL DEFAULT 1,
    eco_number TEXT,
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, item_id, revision),
    UNIQUE (tenant_id, workspace_id, bom_id)
);
ALTER TABLE reconforge.manufacturing_boms ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.manufacturing_boms FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.manufacturing_boms;
CREATE POLICY tenant_scope ON reconforge.manufacturing_boms
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.manufacturing_bom_components (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    bom_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    component_item_id TEXT NOT NULL,
    component_name TEXT NOT NULL,
    component_type TEXT NOT NULL,
    quantity_per_parent INTEGER NOT NULL,
    scrap_factor_bps INTEGER NOT NULL DEFAULT 0,
    substitute_item_id TEXT,
    substitute_ratio_bps INTEGER NOT NULL DEFAULT 10000,
    uom_id TEXT NOT NULL DEFAULT 'EA',
    uom_conversion_factor_bps INTEGER NOT NULL DEFAULT 10000,
    eco_number TEXT,
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, bom_id, line_number)
);
ALTER TABLE reconforge.manufacturing_bom_components ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.manufacturing_bom_components FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.manufacturing_bom_components;
CREATE POLICY tenant_scope ON reconforge.manufacturing_bom_components
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE INDEX IF NOT EXISTS idx_bom_components_lookup
ON reconforge.manufacturing_bom_components (tenant_id, workspace_id, bom_id);

CREATE TABLE IF NOT EXISTS reconforge.treasury_cash_positions (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    bank_account_id TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    cleared_balance_minor BIGINT NOT NULL,
    minimum_covenant_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, legal_entity_id, bank_account_id)
);

CREATE TABLE IF NOT EXISTS reconforge.treasury_liquidity_flows (
    tenant_id TEXT NOT NULL,
    flow_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    currency TEXT NOT NULL,
    due_date DATE NOT NULL,
    amount_minor BIGINT NOT NULL,
    confidence_bps INTEGER NOT NULL DEFAULT 10000,
    status TEXT NOT NULL DEFAULT 'projected',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, flow_id)
);

CREATE INDEX IF NOT EXISTS idx_postgres_treasury_flows_due
    ON reconforge.treasury_liquidity_flows (tenant_id, workspace_id, legal_entity_id, currency, due_date);

ALTER TABLE reconforge.treasury_cash_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.treasury_cash_positions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.treasury_cash_positions;
CREATE POLICY tenant_scope ON reconforge.treasury_cash_positions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE reconforge.treasury_liquidity_flows ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.treasury_liquidity_flows FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.treasury_liquidity_flows;
CREATE POLICY tenant_scope ON reconforge.treasury_liquidity_flows
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.quality_inspection_plans (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    name TEXT NOT NULL,
    sample_size_units INTEGER NOT NULL CHECK (sample_size_units > 0),
    specifications_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, plan_id),
    UNIQUE (tenant_id, workspace_id, item_id, revision)
);
CREATE TABLE IF NOT EXISTS reconforge.quality_ncrs (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    ncr_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    defect_code TEXT NOT NULL,
    defect_severity TEXT NOT NULL,
    inspector_id TEXT NOT NULL,
    quarantined_quantity_scaled BIGINT NOT NULL CHECK (quarantined_quantity_scaled > 0),
    status TEXT NOT NULL,
    disposition TEXT,
    disposition_notes TEXT,
    disposition_by TEXT,
    disposition_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, ncr_id)
);
CREATE TABLE IF NOT EXISTS reconforge.quality_rework_orders (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rework_order_id TEXT NOT NULL,
    parent_work_order_id TEXT NOT NULL,
    ncr_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    rework_quantity_scaled BIGINT NOT NULL CHECK (rework_quantity_scaled > 0),
    rework_routing_steps_json TEXT NOT NULL,
    rework_cost_center TEXT NOT NULL,
    status TEXT NOT NULL,
    accumulated_rework_cost_minor BIGINT NOT NULL DEFAULT 0 CHECK (accumulated_rework_cost_minor >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, workspace_id, rework_order_id),
    FOREIGN KEY (tenant_id, workspace_id, ncr_id)
        REFERENCES reconforge.quality_ncrs(tenant_id, workspace_id, ncr_id)
);
ALTER TABLE reconforge.quality_inspection_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_inspection_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_inspection_plans;
CREATE POLICY tenant_scope ON reconforge.quality_inspection_plans
    USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));
ALTER TABLE reconforge.quality_ncrs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_ncrs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_ncrs;
CREATE POLICY tenant_scope ON reconforge.quality_ncrs
    USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));
ALTER TABLE reconforge.quality_rework_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_rework_orders FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_rework_orders;
CREATE POLICY tenant_scope ON reconforge.quality_rework_orders
    USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));
CREATE INDEX IF NOT EXISTS idx_quality_plan_scope_item
    ON reconforge.quality_inspection_plans(tenant_id,workspace_id,item_id,created_at);
CREATE INDEX IF NOT EXISTS idx_quality_ncr_scope_lot
    ON reconforge.quality_ncrs(tenant_id,workspace_id,lot_id,status);
CREATE INDEX IF NOT EXISTS idx_quality_rework_scope_ncr
    ON reconforge.quality_rework_orders(tenant_id,workspace_id,ncr_id,status);

CREATE TABLE IF NOT EXISTS reconforge.fixed_asset_register_states (
    tenant_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    register_code TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    cost_minor BIGINT NOT NULL,
    salvage_minor BIGINT NOT NULL,
    useful_life_months INTEGER NOT NULL,
    accumulated_depreciation_minor BIGINT NOT NULL DEFAULT 0,
    accumulated_impairment_minor BIGINT NOT NULL DEFAULT 0,
    months_depreciated INTEGER NOT NULL DEFAULT 0,
    carrying_value_minor BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, asset_id, register_code),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES reconforge.fixed_assets(tenant_id, id)
);

ALTER TABLE reconforge.fixed_asset_register_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.fixed_asset_register_states FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.fixed_asset_register_states;
CREATE POLICY tenant_scope ON reconforge.fixed_asset_register_states
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE reconforge.shop_floor_lots ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_lots FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_lots;
CREATE POLICY tenant_scope ON reconforge.shop_floor_lots USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.shop_floor_lots'::regclass AND conname='shop_floor_lots_workspace_fk') THEN ALTER TABLE reconforge.shop_floor_lots ADD CONSTRAINT shop_floor_lots_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.shop_floor_lot_genealogy ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_lot_genealogy FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_lot_genealogy;
CREATE POLICY tenant_scope ON reconforge.shop_floor_lot_genealogy USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.shop_floor_lot_genealogy'::regclass AND conname='shop_floor_lot_genealogy_workspace_fk') THEN ALTER TABLE reconforge.shop_floor_lot_genealogy ADD CONSTRAINT shop_floor_lot_genealogy_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.shop_floor_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_dispatches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_dispatches;
CREATE POLICY tenant_scope ON reconforge.shop_floor_dispatches USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.shop_floor_dispatches'::regclass AND conname='shop_floor_dispatches_workspace_fk') THEN ALTER TABLE reconforge.shop_floor_dispatches ADD CONSTRAINT shop_floor_dispatches_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.shop_floor_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_steps FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_steps;
CREATE POLICY tenant_scope ON reconforge.shop_floor_steps USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.shop_floor_steps'::regclass AND conname='shop_floor_steps_workspace_fk') THEN ALTER TABLE reconforge.shop_floor_steps ADD CONSTRAINT shop_floor_steps_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.project_wbs_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_wbs_tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_wbs_tasks;
CREATE POLICY tenant_scope ON reconforge.project_wbs_tasks USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.project_wbs_tasks'::regclass AND conname='project_wbs_tasks_workspace_fk') THEN ALTER TABLE reconforge.project_wbs_tasks ADD CONSTRAINT project_wbs_tasks_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.project_resource_rate_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_resource_rate_cards FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_resource_rate_cards;
CREATE POLICY tenant_scope ON reconforge.project_resource_rate_cards USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.project_resource_rate_cards'::regclass AND conname='project_resource_rate_cards_workspace_fk') THEN ALTER TABLE reconforge.project_resource_rate_cards ADD CONSTRAINT project_resource_rate_cards_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.project_milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_milestones FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_milestones;
CREATE POLICY tenant_scope ON reconforge.project_milestones USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.project_milestones'::regclass AND conname='project_milestones_workspace_fk') THEN ALTER TABLE reconforge.project_milestones ADD CONSTRAINT project_milestones_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.project_milestone_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_milestone_invoices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_milestone_invoices;
CREATE POLICY tenant_scope ON reconforge.project_milestone_invoices USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.project_milestone_invoices'::regclass AND conname='project_milestone_invoices_workspace_fk') THEN ALTER TABLE reconforge.project_milestone_invoices ADD CONSTRAINT project_milestone_invoices_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.project_time_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_time_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_time_logs;
CREATE POLICY tenant_scope ON reconforge.project_time_logs USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.project_time_logs'::regclass AND conname='project_time_logs_workspace_fk') THEN ALTER TABLE reconforge.project_time_logs ADD CONSTRAINT project_time_logs_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.mps_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.mps_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.mps_plans;
CREATE POLICY tenant_scope ON reconforge.mps_plans USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.mps_plans'::regclass AND conname='mps_plans_workspace_fk') THEN ALTER TABLE reconforge.mps_plans ADD CONSTRAINT mps_plans_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.mps_sourcing_requisitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.mps_sourcing_requisitions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.mps_sourcing_requisitions;
CREATE POLICY tenant_scope ON reconforge.mps_sourcing_requisitions USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.mps_sourcing_requisitions'::regclass AND conname='mps_sourcing_requisitions_workspace_fk') THEN ALTER TABLE reconforge.mps_sourcing_requisitions ADD CONSTRAINT mps_sourcing_requisitions_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.consolidated_statement_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidated_statement_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidated_statement_runs;
CREATE POLICY tenant_scope ON reconforge.consolidated_statement_runs USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.consolidated_statement_runs'::regclass AND conname='consolidated_statement_runs_workspace_fk') THEN ALTER TABLE reconforge.consolidated_statement_runs ADD CONSTRAINT consolidated_statement_runs_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

-- Intercompany artifacts belong to0063, not0151. Preserve that established
-- tenant FORCE-RLS contract and existing workspace/actor foreign keys. Server entry
-- points bind the selected workspace in their repository queries.

ALTER TABLE reconforge.intercompany_profit_in_stock_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_profit_in_stock_rules FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_profit_in_stock_rules;
CREATE POLICY tenant_scope ON reconforge.intercompany_profit_in_stock_rules USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.intercompany_profit_in_stock_rules'::regclass AND conname='intercompany_profit_in_stock_rules_workspace_fk') THEN ALTER TABLE reconforge.intercompany_profit_in_stock_rules ADD CONSTRAINT intercompany_profit_in_stock_rules_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_profit_in_stock_eliminations;
CREATE POLICY tenant_scope ON reconforge.intercompany_profit_in_stock_eliminations USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.intercompany_profit_in_stock_eliminations'::regclass AND conname='intercompany_profit_in_stock_eliminations_workspace_fk') THEN ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations ADD CONSTRAINT intercompany_profit_in_stock_eliminations_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.hcm_leave_entitlement_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.hcm_leave_entitlement_balances FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_entitlement_balances;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_entitlement_balances USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.hcm_leave_entitlement_balances'::regclass AND conname='hcm_leave_entitlement_balances_workspace_fk') THEN ALTER TABLE reconforge.hcm_leave_entitlement_balances ADD CONSTRAINT hcm_leave_entitlement_balances_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.hcm_leave_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.hcm_leave_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_requests;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_requests USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.hcm_leave_requests'::regclass AND conname='hcm_leave_requests_workspace_fk') THEN ALTER TABLE reconforge.hcm_leave_requests ADD CONSTRAINT hcm_leave_requests_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.crm_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_opportunities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_opportunities;
CREATE POLICY tenant_scope ON reconforge.crm_opportunities USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.crm_opportunities'::regclass AND conname='crm_opportunities_workspace_fk') THEN ALTER TABLE reconforge.crm_opportunities ADD CONSTRAINT crm_opportunities_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.crm_quotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotations;
CREATE POLICY tenant_scope ON reconforge.crm_quotations USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.crm_quotations'::regclass AND conname='crm_quotations_workspace_fk') THEN ALTER TABLE reconforge.crm_quotations ADD CONSTRAINT crm_quotations_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.crm_quotation_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotation_lines FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotation_lines;
CREATE POLICY tenant_scope ON reconforge.crm_quotation_lines USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.crm_quotation_lines'::regclass AND conname='crm_quotation_lines_workspace_fk') THEN ALTER TABLE reconforge.crm_quotation_lines ADD CONSTRAINT crm_quotation_lines_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.crm_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_contracts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_contracts;
CREATE POLICY tenant_scope ON reconforge.crm_contracts USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.crm_contracts'::regclass AND conname='crm_contracts_workspace_fk') THEN ALTER TABLE reconforge.crm_contracts ADD CONSTRAINT crm_contracts_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.crm_subscription_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_subscription_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_subscription_plans;
CREATE POLICY tenant_scope ON reconforge.crm_subscription_plans USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.crm_subscription_plans'::regclass AND conname='crm_subscription_plans_workspace_fk') THEN ALTER TABLE reconforge.crm_subscription_plans ADD CONSTRAINT crm_subscription_plans_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.crm_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_subscriptions;
CREATE POLICY tenant_scope ON reconforge.crm_subscriptions USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.crm_subscriptions'::regclass AND conname='crm_subscriptions_workspace_fk') THEN ALTER TABLE reconforge.crm_subscriptions ADD CONSTRAINT crm_subscriptions_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.workcenter_calendars ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.workcenter_calendars FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.workcenter_calendars;
CREATE POLICY tenant_scope ON reconforge.workcenter_calendars USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.workcenter_calendars'::regclass AND conname='workcenter_calendars_workspace_fk') THEN ALTER TABLE reconforge.workcenter_calendars ADD CONSTRAINT workcenter_calendars_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.workcenter_shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.workcenter_shifts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.workcenter_shifts;
CREATE POLICY tenant_scope ON reconforge.workcenter_shifts USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.workcenter_shifts'::regclass AND conname='workcenter_shifts_workspace_fk') THEN ALTER TABLE reconforge.workcenter_shifts ADD CONSTRAINT workcenter_shifts_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.capacity_slot_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.capacity_slot_reservations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.capacity_slot_reservations;
CREATE POLICY tenant_scope ON reconforge.capacity_slot_reservations USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.capacity_slot_reservations'::regclass AND conname='capacity_slot_reservations_workspace_fk') THEN ALTER TABLE reconforge.capacity_slot_reservations ADD CONSTRAINT capacity_slot_reservations_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.manufacturing_boms ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.manufacturing_boms FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.manufacturing_boms;
CREATE POLICY tenant_scope ON reconforge.manufacturing_boms USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.manufacturing_boms'::regclass AND conname='manufacturing_boms_workspace_fk') THEN ALTER TABLE reconforge.manufacturing_boms ADD CONSTRAINT manufacturing_boms_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.manufacturing_bom_components ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.manufacturing_bom_components FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.manufacturing_bom_components;
CREATE POLICY tenant_scope ON reconforge.manufacturing_bom_components USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.manufacturing_bom_components'::regclass AND conname='manufacturing_bom_components_workspace_fk') THEN ALTER TABLE reconforge.manufacturing_bom_components ADD CONSTRAINT manufacturing_bom_components_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.treasury_cash_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.treasury_cash_positions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.treasury_cash_positions;
CREATE POLICY tenant_scope ON reconforge.treasury_cash_positions USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true) AND organization_id = current_setting('app.organization_id',true) AND legal_entity_id = current_setting('app.legal_entity_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true) AND organization_id = current_setting('app.organization_id',true) AND legal_entity_id = current_setting('app.legal_entity_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.treasury_cash_positions'::regclass AND conname='treasury_cash_positions_workspace_fk') THEN ALTER TABLE reconforge.treasury_cash_positions ADD CONSTRAINT treasury_cash_positions_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.treasury_liquidity_flows ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.treasury_liquidity_flows FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.treasury_liquidity_flows;
CREATE POLICY tenant_scope ON reconforge.treasury_liquidity_flows USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true) AND organization_id = current_setting('app.organization_id',true) AND legal_entity_id = current_setting('app.legal_entity_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true) AND organization_id = current_setting('app.organization_id',true) AND legal_entity_id = current_setting('app.legal_entity_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.treasury_liquidity_flows'::regclass AND conname='treasury_liquidity_flows_workspace_fk') THEN ALTER TABLE reconforge.treasury_liquidity_flows ADD CONSTRAINT treasury_liquidity_flows_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.quality_inspection_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_inspection_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_inspection_plans;
CREATE POLICY tenant_scope ON reconforge.quality_inspection_plans USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.quality_inspection_plans'::regclass AND conname='quality_inspection_plans_workspace_fk') THEN ALTER TABLE reconforge.quality_inspection_plans ADD CONSTRAINT quality_inspection_plans_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.quality_ncrs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_ncrs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_ncrs;
CREATE POLICY tenant_scope ON reconforge.quality_ncrs USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.quality_ncrs'::regclass AND conname='quality_ncrs_workspace_fk') THEN ALTER TABLE reconforge.quality_ncrs ADD CONSTRAINT quality_ncrs_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.quality_rework_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_rework_orders FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_rework_orders;
CREATE POLICY tenant_scope ON reconforge.quality_rework_orders USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.quality_rework_orders'::regclass AND conname='quality_rework_orders_workspace_fk') THEN ALTER TABLE reconforge.quality_rework_orders ADD CONSTRAINT quality_rework_orders_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;

ALTER TABLE reconforge.fixed_asset_register_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.fixed_asset_register_states FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.fixed_asset_register_states;
CREATE POLICY tenant_scope ON reconforge.fixed_asset_register_states USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true)) WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.fixed_asset_register_states'::regclass AND conname='fixed_asset_register_states_workspace_fk') THEN ALTER TABLE reconforge.fixed_asset_register_states ADD CONSTRAINT fixed_asset_register_states_workspace_fk FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id); END IF; END $$;
"""

DOWNGRADE_SQL = r"""
DO $$ BEGIN
IF EXISTS (SELECT 1 FROM reconforge.fixed_asset_register_states) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.quality_rework_orders) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.quality_ncrs) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.quality_inspection_plans) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.treasury_liquidity_flows) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.treasury_cash_positions) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.manufacturing_bom_components) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.manufacturing_boms) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.capacity_slot_reservations) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.workcenter_shifts) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.workcenter_calendars) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.crm_subscriptions) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.crm_subscription_plans) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.crm_contracts) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.crm_quotation_lines) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.crm_quotations) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.crm_opportunities) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.hcm_leave_requests) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
IF EXISTS (SELECT 1 FROM reconforge.hcm_leave_entitlement_balances) THEN RAISE EXCEPTION 'Populated module tables prevent downgrade; retain data and use forward recovery'; END IF;
END $$;
DROP TABLE reconforge.fixed_asset_register_states;
DROP TABLE reconforge.quality_rework_orders;
DROP TABLE reconforge.quality_ncrs;
DROP TABLE reconforge.quality_inspection_plans;
DROP TABLE reconforge.treasury_liquidity_flows;
DROP TABLE reconforge.treasury_cash_positions;
DROP TABLE reconforge.manufacturing_bom_components;
DROP TABLE reconforge.manufacturing_boms;
DROP TABLE reconforge.capacity_slot_reservations;
DROP TABLE reconforge.workcenter_shifts;
DROP TABLE reconforge.workcenter_calendars;
DROP TABLE reconforge.crm_subscriptions;
DROP TABLE reconforge.crm_subscription_plans;
DROP TABLE reconforge.crm_contracts;
DROP TABLE reconforge.crm_quotation_lines;
DROP TABLE reconforge.crm_quotations;
DROP TABLE reconforge.crm_opportunities;
DROP TABLE reconforge.hcm_leave_requests;
DROP TABLE reconforge.hcm_leave_entitlement_balances;
"""
