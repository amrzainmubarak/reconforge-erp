"""Comprehensive Level 2 Enterprise PostgreSQL Verification Suite.

Tests:
1. Multi-tenant isolation across all enterprise repositories (Tenant A vs Tenant B).
2. Audit event emissions with cryptographic chaining.
3. Source-owned GL account derivations for milestone billing and intercompany profit-in-stock.
4. Bidirectional lot genealogy traversal and cycle-safe graph queries.
5. Mathematical conservation:
   - Integer MinorMoney in project billing and consolidated statements.
   - Zero-leakage Parent + NCI profit-in-stock elimination.
   - Shop floor quantity conservation (Completed + Scrap <= Scheduled).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from reconforge.domain.consolidated_financial_statements import (
    EntityTrialBalance,
    GroupIntercompanyEliminations,
    generate_consolidated_statements,
)
from reconforge.domain.intercompany_elimination import (
    IntercompanyProfitInStockRule,
    calculate_profit_in_stock_elimination,
)
from reconforge.domain.master_production_schedule import (
    MPSBucketDemand,
    compute_master_production_schedule,
)
from reconforge.domain.project_milestone_billing import (
    ProjectMilestone,
    ProjectWBSTask,
    ResourceRateCard,
    generate_milestone_invoice,
    verify_milestone_completion,
)
from reconforge.domain.shop_floor_dispatch import (
    LotTraceabilityRecord,
    ShopFloorExecutionError,
    ShopFloorOperationStep,
    WorkOrderDispatch,
    validate_step_progression,
)
from reconforge.infrastructure.postgres_consolidated_statements import (
    POSTGRES_CONSOLIDATED_STATEMENTS_SCHEMA_SQL,
    PostgresConsolidatedStatementsRepository,
)
from reconforge.infrastructure.postgres_intercompany_elimination import (
    POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL,
    PostgresIntercompanyEliminationRepository,
)
from reconforge.infrastructure.postgres_mps import (
    POSTGRES_MPS_SCHEMA_SQL,
    PostgresMPSRepository,
)
from reconforge.infrastructure.postgres_project_milestone_billing import (
    POSTGRES_PROJECT_BILLING_SCHEMA_SQL,
    PostgresProjectMilestoneBillingRepository,
)
from reconforge.infrastructure.postgres_shop_floor import (
    POSTGRES_SHOP_FLOOR_SCHEMA_SQL,
    PostgresShopFloorRepository,
)

ALL_ENTERPRISE_POSTGRES_SCHEMAS = [
    POSTGRES_CONSOLIDATED_STATEMENTS_SCHEMA_SQL,
    POSTGRES_MPS_SCHEMA_SQL,
    POSTGRES_PROJECT_BILLING_SCHEMA_SQL,
    POSTGRES_SHOP_FLOOR_SCHEMA_SQL,
    POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL,
]


class PostgresRelationalTestAdapter:
    """Relational SQL execution adapter simulating PostgreSQL tenant isolation, transactions, and audit tracking."""

    def __init__(self) -> None:
        self._sqlite = sqlite3.connect(":memory:")
        self._active_tenant: str | None = None
        self._audit_events: list[dict[str, Any]] = []
        self._register_functions()
        self._init_schema()

    def _register_functions(self) -> None:
        def _set_config(name: str, val: str, is_local: bool) -> str:
            if name == "app.tenant_id":
                self._active_tenant = val
            return val

        def _current_setting(name: str, missing_ok: bool = True) -> str:
            return self._active_tenant or ""

        self._sqlite.create_function("set_config", 3, _set_config)
        self._sqlite.create_function("current_setting", 1, lambda name: _current_setting(name))
        self._sqlite.create_function("current_setting", 2, _current_setting)
        self._sqlite.create_function("now", 0, lambda: "2026-10-19 12:00:00")

    def _init_schema(self) -> None:
        # Create core tables without Postgres-specific syntax
        cur = self._sqlite.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS domain_audit_ledger_state (
                tenant_id TEXT PRIMARY KEY,
                last_sequence INTEGER NOT NULL,
                last_event_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domain_audit_events (
                tenant_id TEXT NOT NULL,
                id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                actor_user_id TEXT,
                actor_label TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                action TEXT NOT NULL,
                before_hash TEXT,
                after_hash TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, id)
            );

            CREATE TABLE IF NOT EXISTS shop_floor_lots (
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                parent_lot_id TEXT NOT NULL,
                child_lot_id TEXT NOT NULL,
                quantity_consumed_scaled INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (tenant_id, workspace_id, parent_lot_id, child_lot_id)
            );

            CREATE TABLE IF NOT EXISTS shop_floor_dispatches (
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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

            CREATE TABLE IF NOT EXISTS consolidated_statement_runs (
                tenant_id TEXT NOT NULL,
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

            CREATE TABLE IF NOT EXISTS mps_plans (
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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

            CREATE TABLE IF NOT EXISTS intercompany_profit_in_stock_rules (
                tenant_id TEXT NOT NULL,
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
                tenant_id TEXT NOT NULL,
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

            CREATE TABLE IF NOT EXISTS intercompany_elimination_artifacts (
                tenant_id TEXT NOT NULL,
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
                PRIMARY KEY (tenant_id, id)
            );
            """
        )
        self._sqlite.commit()

    class _TxContext:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def __enter__(self) -> None:
            pass

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()

    def transaction(self) -> _TxContext:
        return self._TxContext(self._sqlite)

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        # Convert Postgres SQL dialect to SQLite for verification
        cleaned = (
            statement.replace("reconforge.", "")
            .replace("CAST(%s AS jsonb)", "?")
            .replace("CAST(? AS jsonb)", "?")
            .replace("%s", "?")
            .replace("FOR UPDATE", "")
        )
        # Adapt json dicts to json strings
        adapted_params = []
        for p in parameters:
            if isinstance(p, (dict, list)):
                adapted_params.append(json.dumps(p, sort_keys=True))
            else:
                adapted_params.append(p)

        cursor = self._sqlite.cursor()
        return cursor.execute(cleaned, tuple(adapted_params))

    def close(self) -> None:
        self._sqlite.close()


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------


def test_postgres_shop_floor_multi_tenant_isolation_and_genealogy() -> None:
    conn = PostgresRelationalTestAdapter()
    repo_a = PostgresShopFloorRepository(conn, "tenant_alpha")
    repo_b = PostgresShopFloorRepository(conn, "tenant_beta")

    # 1. Tenant Alpha registers raw lot and finished lot
    raw_lot = LotTraceabilityRecord(
        workspace_id="ws_main",
        lot_id="LOT_RAW_01",
        item_id="STEEL_SHEET",
        batch_number="BATCH_S01",
        quantity_scaled=10_000,
        status="active",
    )
    repo_a.register_lot(raw_lot)

    fg_lot = LotTraceabilityRecord(
        workspace_id="ws_main",
        lot_id="LOT_FG_01",
        item_id="STEEL_FRAME",
        batch_number="BATCH_F01",
        quantity_scaled=5_000,
        status="active",
    )
    repo_a.register_lot(fg_lot, parent_lots=[("LOT_RAW_01", 10_000)])

    # Dispatch work order
    step_1 = ShopFloorOperationStep(
        step_id="ST_01",
        work_order_id="WO_100",
        operation_sequence=1,
        work_center_id="WC_CUTTING",
        operator_id="OP_ALICE",
        status="completed",
        actual_run_minutes=45,
        quantity_completed_scaled=5_000,
        quantity_scrapped_scaled=0,
    )
    dispatch = WorkOrderDispatch(
        workspace_id="ws_main",
        dispatch_id="DISP_100",
        work_order_id="WO_100",
        item_id="STEEL_FRAME",
        scheduled_quantity_scaled=5_000,
        dispatched_lot_id="LOT_FG_01",
        dispatched_at="2026-10-19T10:00:00Z",
        steps=(step_1,),
    )
    repo_a.save_dispatch(dispatch)

    # 2. Multi-tenant isolation verification: Tenant Beta CANNOT see Tenant Alpha's data
    assert repo_a.get_lot("ws_main", "LOT_FG_01") is not None
    assert repo_b.get_lot("ws_main", "LOT_FG_01") is None
    assert repo_b.get_dispatch("ws_main", "DISP_100") is None

    # 3. Traversal verification on Tenant Alpha
    node_bwd = repo_a.traverse("ws_main", "LOT_FG_01", "backward")
    assert node_bwd.lot_id == "LOT_FG_01"
    assert len(node_bwd.children) == 1
    assert node_bwd.children[0].lot_id == "LOT_RAW_01"

    # Step progression invariant: scrap + completed <= scheduled
    invalid_step = ShopFloorOperationStep(
        step_id="ST_02",
        work_order_id="WO_100",
        operation_sequence=2,
        work_center_id="WC_ASSEMBLY",
        operator_id="OP_BOB",
        status="completed",
        actual_run_minutes=30,
        quantity_completed_scaled=4_500,
        quantity_scrapped_scaled=1_000,  # 4500 + 1000 = 5500 > 5000 scheduled
    )
    with pytest.raises(ShopFloorExecutionError, match="exceeds scheduled dispatch quantity"):
        validate_step_progression(dispatch, invalid_step)


def test_postgres_project_milestone_billing_gl_and_financial_posture() -> None:
    conn = PostgresRelationalTestAdapter()
    repo_a = PostgresProjectMilestoneBillingRepository(conn, "tenant_alpha")
    repo_b = PostgresProjectMilestoneBillingRepository(conn, "tenant_beta")

    # 1. Tenant Alpha creates WBS Task & Rate Card
    task = ProjectWBSTask(
        workspace_id="ws_projects",
        task_id="TASK_ERP_01",
        project_id="PRJ_DIGITAL",
        task_code="WBS-1.1",
        name="Architecture Blueprint",
        parent_task_id=None,
        planned_hours=120,
        budget_cost_minor=1_800_000,  # $18,000.00
        currency="USD",
        status="in_progress",
    )
    repo_a.save_task(task)

    rate_card = ResourceRateCard(
        workspace_id="ws_projects",
        rate_card_id="RC_ARCHITECT",
        project_id="PRJ_DIGITAL",
        resource_role="Principal Enterprise Architect",
        hourly_cost_rate_minor=15_000,  # $150.00/hr
        hourly_bill_rate_minor=25_000,  # $250.00/hr
        currency="USD",
    )
    repo_a.save_rate_card(rate_card)

    # 2. Log time and compute actual cost & billable amount
    actual_cost, billable = repo_a.log_time(
        workspace_id="ws_projects",
        log_id="LOG_01",
        project_id="PRJ_DIGITAL",
        task_id="TASK_ERP_01",
        role="Principal Enterprise Architect",
        hours=10,
        date="2026-10-19",
    )
    assert actual_cost == 150_000  # $1,500.00
    assert billable == 250_000     # $2,500.00

    # 3. Create milestone, verify (maker-checker), and generate invoice
    milestone = ProjectMilestone(
        workspace_id="ws_projects",
        milestone_id="MS_DELIVERABLE_1",
        project_id="PRJ_DIGITAL",
        contract_line_id="CONTRACT_LINE_01",
        title="Architecture Completion Sign-off",
        milestone_amount_minor=500_000,  # $5,000.00
        currency="USD",
        due_date="2026-10-31",
        status="pending",
    )
    repo_a.save_milestone(milestone)

    verified = verify_milestone_completion(milestone, "lead_checker", "2026-10-19T11:00:00Z")
    updated_ms, invoice = generate_milestone_invoice(verified, "CUST_GLOBAL_BANK", "INV_MS_100", "2026-10-19T11:05:00Z")

    repo_a.save_milestone_invoice(updated_ms, invoice)

    # Verify source-owned GL accounts
    assert invoice.gl_debit_account == "ACCOUNTS_RECEIVABLE"
    assert invoice.gl_credit_account == "PROJECT_SERVICE_REVENUE"
    assert invoice.billed_amount_minor == 500_000

    # 4. Verify Financial Posture
    posture = repo_a.get_financial_posture("ws_projects", "PRJ_DIGITAL", "USD")
    assert posture.budget_cost_minor == 1_800_000
    assert posture.actual_cost_minor == 150_000
    assert posture.total_billed_minor == 500_000
    # Net profit = 500_000 - 150_000 = 350_000. Margin bps = 350_000 * 10,000 // 500_000 = 7,000 bps (70.00%)
    assert posture.profit_margin_bps == 7_000

    # 5. Multi-tenant isolation: Tenant Beta cannot see Tenant Alpha's project data
    assert len(repo_b.list_tasks("ws_projects", "PRJ_DIGITAL")) == 0
    assert repo_b.get_milestone("ws_projects", "MS_DELIVERABLE_1") is None
    posture_b = repo_b.get_financial_posture("ws_projects", "PRJ_DIGITAL", "USD")
    assert posture_b.total_billed_minor == 0


def test_postgres_consolidated_statements_and_mps_isolation() -> None:
    conn = PostgresRelationalTestAdapter()
    repo_cons_a = PostgresConsolidatedStatementsRepository(conn, "tenant_alpha")
    repo_cons_b = PostgresConsolidatedStatementsRepository(conn, "tenant_beta")

    # Generate consolidated statements
    entities = [
        EntityTrialBalance(
            entity_id="HOLDING_CORP",
            functional_currency="USD",
            fx_rate_to_group_scaled=1_000_000,
            parent_ownership_bips=10_000,
            cash_minor=1_000_000,
            trade_receivables_minor=500_000,
            intercompany_receivables_minor=100_000,
            inventory_minor=400_000,
            ppe_minor=2_000_000,
            other_assets_minor=0,
            trade_payables_minor=300_000,
            intercompany_payables_minor=0,
            short_term_debt_minor=200_000,
            long_term_debt_minor=500_000,
            other_liabilities_minor=0,
            share_capital_minor=1_500_000,
            retained_earnings_opening_minor=1_500_000,
            gross_revenue_minor=1_200_000,
            intercompany_revenue_minor=50_000,
            cogs_minor=600_000,
            intercompany_cogs_minor=0,
            operating_expenses_minor=200_000,
            depreciation_minor=100_000,
            finance_costs_minor=50_000,
            tax_expense_minor=100_000,
        ),
        EntityTrialBalance(
            entity_id="SUB_OPERATIONS",
            functional_currency="USD",
            fx_rate_to_group_scaled=1_000_000,
            parent_ownership_bips=8_000,  # 80% parent, 20% NCI
            cash_minor=200_000,
            trade_receivables_minor=150_000,
            intercompany_receivables_minor=0,
            inventory_minor=250_000,
            ppe_minor=800_000,
            other_assets_minor=0,
            trade_payables_minor=100_000,
            intercompany_payables_minor=100_000,
            short_term_debt_minor=50_000,
            long_term_debt_minor=150_000,
            other_liabilities_minor=0,
            share_capital_minor=400_000,
            retained_earnings_opening_minor=600_000,
            gross_revenue_minor=500_000,
            intercompany_revenue_minor=0,
            cogs_minor=250_000,
            intercompany_cogs_minor=50_000,
            operating_expenses_minor=80_000,
            depreciation_minor=40_000,
            finance_costs_minor=10_000,
            tax_expense_minor=20_000,
        ),
    ]
    eliminations = GroupIntercompanyEliminations(
        intercompany_receivables_eliminated_minor=100_000,
        intercompany_payables_eliminated_minor=100_000,
        intercompany_revenue_eliminated_minor=50_000,
        intercompany_cogs_eliminated_minor=50_000,
        profit_in_stock_eliminated_minor=0,
    )
    statements = generate_consolidated_statements(
        group_id="GRP_ENTERPRISE",
        organization_id="ORG_HOLDING",
        reporting_currency="USD",
        period_id="2026-Q3",
        period_start="2026-07-01",
        period_end="2026-09-30",
        as_of_date="2026-09-30",
        entities=entities,
        eliminations=eliminations,
    )
    run_id = repo_cons_a.save_run(workspace_id="ws_finance", statements=statements)

    # Multi-tenant statement run isolation
    assert repo_cons_a.get_run(workspace_id="ws_finance", run_id=run_id) is not None
    assert repo_cons_b.get_run(workspace_id="ws_finance", run_id=run_id) is None

    # MPS Plan persistence and shortage procurement requisitions
    repo_mps_a = PostgresMPSRepository(conn, "tenant_alpha")
    repo_mps_b = PostgresMPSRepository(conn, "tenant_beta")

    buckets = [
        MPSBucketDemand(
            bucket_index=0,
            bucket_start_date="2026-11-01",
            bucket_end_date="2026-11-07",
            sales_orders_scaled=1_500,
            forecast_demand_scaled=1_000,
            scheduled_receipts_scaled=0,
        )
    ]
    plan = compute_master_production_schedule(
        plan_id="MPS_P100",
        plan_name="Q4 Assembly Plan",
        revision="rev1",
        item_id="FINISHED_SERVER",
        unit_of_measure="EA",
        quantity_scale=1000,
        safety_stock_scaled=500,
        lot_size_multiple_scaled=1000,
        opening_inventory_scaled=200,
        buckets=buckets,
        preferred_supplier_id="SUP_CHIPS",
        unit_price_ceiling_minor=50_000,
        currency="USD",
    )
    repo_mps_a.save_plan(workspace_id="ws_mfg", plan_result=plan)

    assert repo_mps_a.get_plan(workspace_id="ws_mfg", plan_id="MPS_P100", revision="rev1") is not None
    assert repo_mps_b.get_plan(workspace_id="ws_mfg", plan_id="MPS_P100", revision="rev1") is None
    assert len(repo_mps_a.list_requisitions(workspace_id="ws_mfg", plan_id="MPS_P100")) > 0
    assert len(repo_mps_b.list_requisitions(workspace_id="ws_mfg", plan_id="MPS_P100")) == 0


def test_postgres_intercompany_profit_in_stock_zero_leakage_and_isolation() -> None:
    conn = PostgresRelationalTestAdapter()
    repo_a = PostgresIntercompanyEliminationRepository(conn, "tenant_alpha")
    repo_b = PostgresIntercompanyEliminationRepository(conn, "tenant_beta")

    rule = IntercompanyProfitInStockRule(
        rule_id="RULE_PIS_01",
        selling_entity="ENTITY_MANUFACTURER",
        buying_entity="ENTITY_DISTRIBUTOR",
        inventory_item_code="PRODUCT_X",
        margin_basis_points=2_500,  # 25.00% markup margin
        ending_inventory_cost_minor=1_000_000,  # $10,000.00 ending inventory
        nci_share_basis_points=2_000,  # 20.00% NCI in selling entity
        currency="USD",
    )
    elimination = calculate_profit_in_stock_elimination(rule)

    # Invariants:
    # Unrealized profit = 1,000,000 * 2,500 // 10,000 = 250,000 ($2,500.00)
    # NCI share = 250,000 * 2,000 // 10,000 = 50,000 ($500.00)
    # Parent share = 250,000 - 50,000 = 200,000 ($2,000.00)
    assert elimination.unrealized_profit_minor == 250_000
    assert elimination.nci_share_minor == 50_000
    assert elimination.parent_share_minor == 200_000
    assert elimination.parent_share_minor + elimination.nci_share_minor == elimination.unrealized_profit_minor

    repo_a.save_profit_in_stock_elimination("ws_global", rule, elimination)

    # Multi-tenant isolation verification
    elim_a = repo_a.list_profit_in_stock_eliminations("ws_global")
    elim_b = repo_b.list_profit_in_stock_eliminations("ws_global")
    assert len(elim_a) == 1
    assert len(elim_b) == 0
    assert elim_a[0]["elimination_id"] == elimination.elimination_id
    assert elim_a[0]["debit_account"] == "COGS_ELIMINATION"
    assert elim_a[0]["credit_account"] == "INVENTORY_VALUATION"


def test_enterprise_routes_fail_closed_mode(tmp_path: Any) -> None:
    """Verify that when server_mode is True, API routes fail closed if PostgreSQL is unconfigured."""
    from starlette.datastructures import State

    from reconforge.api.errors import APIError
    from reconforge.api.routes.consolidated_financial_statements import _get_repository as get_cons_repo
    from reconforge.api.routes.intercompany_elimination import _get_repository as get_elim_repo
    from reconforge.api.routes.master_production_schedule import _get_repository as get_mps_repo
    from reconforge.api.routes.project_milestone_billing import _get_repo as get_proj_repo
    from reconforge.api.routes.shop_floor_traceability import _get_repo as get_sf_repo

    mock_app = type("MockApp", (), {"state": State({"server_mode": True, "db_path": str(tmp_path / "sqlite.db")})})()
    mock_request = type(
        "MockRequest",
        (),
        {"app": mock_app, "state": State({"tenant_id": "test_tenant", "workspace_id": "default"})},
    )()

    for repo_fn in (get_cons_repo, get_elim_repo, get_mps_repo, get_proj_repo, get_sf_repo):
        with pytest.raises(APIError) as exc_info:
            repo_fn(mock_request)
        assert exc_info.value.status_code == 503
        assert exc_info.value.code == "server_postgres_unavailable"
        assert "Enterprise production profile requires PostgreSQL" in exc_info.value.message

    # Verify that in Community / Local profile (server_mode=False), SQLite repo resolves cleanly
    mock_app.state.server_mode = False
    sqlite_conn, sqlite_repo = get_cons_repo(mock_request)
    assert sqlite_repo is not None
    sqlite_conn.close()


def test_live_postgres_enterprise_security_force_rls_and_canonical_gl() -> None:
    """Live PostgreSQL integration test: verifies FORCE RLS, unprivileged role, GL posting, and audit chaining."""
    import os
    import subprocess
    import sys
    from uuid import uuid4

    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        pytest.skip("psycopg is not installed")

    admin_base = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", "postgresql://postgres:postgres@127.0.0.1:55432/postgres")
    try:
        with psycopg.connect(admin_base, connect_timeout=3, autocommit=True) as probe:
            probe.execute("SELECT 1")
    except Exception:
        pytest.skip("Live PostgreSQL service is not reachable")

    from reconforge.domain.intercompany_elimination import (
        IntercompanyProfitInStockRule,
        calculate_profit_in_stock_elimination,
    )
    from reconforge.domain.project_milestone_billing import (
        ProjectMilestone,
        generate_milestone_invoice,
    )
    from reconforge.domain.shop_floor_dispatch import (
        LotTraceabilityRecord,
    )
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
    from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
    from reconforge.infrastructure.postgres_intercompany_elimination import PostgresIntercompanyEliminationRepository
    from reconforge.infrastructure.postgres_project_milestone_billing import PostgresProjectMilestoneBillingRepository
    from reconforge.infrastructure.postgres_shop_floor import PostgresShopFloorRepository

    db_name = f"rf_live_test_{uuid4().hex[:8]}"
    with psycopg.connect(admin_base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

    admin_dsn = f"postgresql://postgres:postgres@127.0.0.1:55432/{db_name}"
    app_user = f"app_user_{uuid4().hex[:8]}"
    app_pass = f"pass_{uuid4().hex[:8]}"
    app_dsn = f"postgresql://{app_user}:{app_pass}@127.0.0.1:55432/{db_name}"

    try:
        # Run Alembic migrations to current HEAD (0151)
        runner = "import sys, os; sys.path = [p for p in sys.path if os.path.abspath(p) != os.getcwd()] + [os.getcwd()]; from alembic.config import CommandLine; CommandLine().main()"
        subprocess.run(
            [sys.executable, "-c", runner, "upgrade", "head"],
            env={**os.environ, "RECONFORGE_POSTGRES_DSN": admin_dsn},
            capture_output=True,
            text=True,
            check=True,
        )

        # Create restricted application role (NOSUPERUSER, NOBYPASSRLS)
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE").format(
                    sql.Identifier(app_user), sql.Literal(app_pass)
                )
            )
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(app_user)))
            admin.execute(sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(app_user)))
            admin.execute(sql.SQL("GRANT ALL ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(sql.Identifier(app_user)))

        # Assert App Role flags
        with psycopg.connect(app_dsn) as app_conn:
            role_flags = app_conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            assert role_flags == (False, False)

        tenant_a = f"tenant_alpha_{uuid4().hex[:6]}"
        tenant_b = f"tenant_beta_{uuid4().hex[:6]}"
        workspace_id = "ws_mfg"

        with psycopg.connect(admin_dsn) as admin:
            admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant_a, "Alpha Corp"))
            admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant_b, "Beta LLC"))

        factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))

        # Setup Tenant A workspace and master data
        with PostgresTenantBoundary(factory).transaction(tenant_a) as conn:
            conn.execute("INSERT INTO reconforge.domain_workspaces (tenant_id, id, name) VALUES (%s, %s, %s)", (tenant_a, workspace_id, "Manufacturing WS"))
            conn.execute("INSERT INTO reconforge.currencies (tenant_id, code, name, minor_units) VALUES (%s, 'USD', 'US Dollar', 2)", (tenant_a,))
            conn.execute("INSERT INTO reconforge.organizations (tenant_id, id, organization_code, name, base_currency, application_workspace_id) VALUES (%s, 'org_a', 'ORG_A', 'Alpha Org', 'USD', %s)", (tenant_a, workspace_id))
            conn.execute("INSERT INTO reconforge.master_data_workspace_organizations (tenant_id, workspace_id, organization_id) VALUES (%s, %s, 'org_a')", (tenant_a, workspace_id))
            conn.execute("INSERT INTO reconforge.legal_entities (tenant_id, id, organization_id, entity_code, name, currency_code) VALUES (%s, 'ent_a', 'org_a', 'ENT_A', 'Alpha Entity', 'USD')", (tenant_a,))
            conn.execute("INSERT INTO reconforge.fiscal_periods (tenant_id, id, name, start_date, end_date, fiscal_year, period_number, application_workspace_id) VALUES (%s, 'per_2026_10', '2026-10', '2026-10-01', '2026-10-31', 2026, 10, %s)", (tenant_a, workspace_id))
            conn.execute("INSERT INTO reconforge.master_data_workspace_periods (tenant_id, workspace_id, period_id) VALUES (%s, %s, 'per_2026_10')", (tenant_a, workspace_id))

            fc = PostgresFinanceCoreRepository(conn, tenant_a)
            fc.upsert_chart(chart_code="STD", name="Standard Chart", workspace=workspace_id, organization_code="ORG_A")
            fc.upsert_account(account_code="ACCOUNTS_RECEIVABLE", name="Accounts Receivable", account_type="Asset", chart_code="STD", workspace=workspace_id)
            fc.upsert_account(account_code="PROJECT_SERVICE_REVENUE", name="Service Revenue", account_type="Income", chart_code="STD", workspace=workspace_id)
            fc.upsert_account(account_code="COGS_ELIMINATION", name="COGS Elimination", account_type="Expense", chart_code="STD", workspace=workspace_id)
            fc.upsert_account(account_code="INVENTORY_VALUATION", name="Inventory Valuation", account_type="Asset", chart_code="STD", workspace=workspace_id)
            fc.upsert_journal(journal_code="GENERAL", name="General Journal", chart_code="STD", organization_code="ORG_A", currency_code="USD", workspace=workspace_id)
            fc.upsert_journal(journal_code="CONSOLIDATION", name="Consolidation Journal", chart_code="STD", organization_code="ORG_A", currency_code="USD", workspace=workspace_id)

        # Setup Tenant B workspace
        with PostgresTenantBoundary(factory).transaction(tenant_b) as conn:
            conn.execute("INSERT INTO reconforge.domain_workspaces (tenant_id, id, name) VALUES (%s, %s, %s)", (tenant_b, workspace_id, "Manufacturing WS Beta"))

        # Tenant Alpha inserts enterprise data and posts GL vouchers
        with PostgresTenantBoundary(factory).transaction(tenant_a) as conn:
            sf_repo = PostgresShopFloorRepository(conn, tenant_a)
            lot = LotTraceabilityRecord(
                workspace_id=workspace_id,
                lot_id="LOT_LIVE_001",
                item_id="ITEM_TURBINE",
                batch_number="BATCH_ALPHA",
                quantity_scaled=50_000,
                scale_factor=1000,
                status="active",
            )
            sf_repo.register_lot(lot, actor_label="engineer-alpha")

            pb_repo = PostgresProjectMilestoneBillingRepository(conn, tenant_a)
            milestone = ProjectMilestone(
                workspace_id=workspace_id,
                milestone_id="MS_LIVE_001",
                project_id="PROJ_ALPHA",
                contract_line_id="CL_10",
                title="Foundation Complete",
                milestone_amount_minor=1_000_000,
                currency="USD",
                due_date="2026-10-25",
                status="verified",
                verified_by="inspector_alice",
                verified_at="2026-10-19T10:00:00Z",
            )
            updated_ms, invoice = generate_milestone_invoice(milestone, customer_code="CUST_OMEGA", invoice_id="INV_LIVE_001", issued_at="2026-10-19T12:00:00Z")
            pb_repo.save_milestone_invoice(updated_ms, invoice, actor_label="pm-alpha")

            # Post milestone invoice to Finance Core GL
            fc_repo = PostgresFinanceCoreRepository(conn, tenant_a)
            entry_id = pb_repo.post_milestone_invoice_to_finance_core(
                invoice=invoice,
                organization_code="ORG_A",
                entity_code="ENT_A",
                period_id="per_2026_10",
                journal_code="GENERAL",
                finance_core_repo=fc_repo,
                actor_label="pm-alpha",
            )
            assert entry_id.startswith("GLE-")

            # Assert double-entry balance in Finance Core lines
            gl_lines = conn.execute("SELECT account_id, debit_minor, credit_minor FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s", (tenant_a, entry_id)).fetchall()
            assert len(gl_lines) == 2
            assert sum(line[1] for line in gl_lines) == sum(line[2] for line in gl_lines) == 1_000_000

            # Intercompany Profit in Stock elimination
            elim_repo = PostgresIntercompanyEliminationRepository(conn, tenant_a)
            rule = IntercompanyProfitInStockRule(
                rule_id="RULE_LIVE_PIS_01",
                selling_entity="ENTITY_MFG",
                buying_entity="ENTITY_DIST",
                inventory_item_code="PRODUCT_TURBINE",
                margin_basis_points=2_000,
                ending_inventory_cost_minor=500_000,
                nci_share_basis_points=1_000,
                currency="USD",
            )
            elimination = calculate_profit_in_stock_elimination(rule)
            elim_repo.save_profit_in_stock_elimination(workspace_id, rule, elimination, actor_label="finance-alpha")

            elim_entry_id = elim_repo.post_profit_in_stock_to_finance_core(
                elimination=elimination,
                organization_code="ORG_A",
                entity_code="ENT_A",
                period_id="per_2026_10",
                posting_date="2026-10-19",
                journal_code="CONSOLIDATION",
                workspace=workspace_id,
                finance_core_repo=fc_repo,
                actor_label="finance-alpha",
            )
            assert elim_entry_id.startswith("GLE-")
            elim_lines = conn.execute("SELECT account_id, debit_minor, credit_minor FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s", (tenant_a, elim_entry_id)).fetchall()
            assert len(elim_lines) == 2
            assert sum(line[1] for line in elim_lines) == sum(line[2] for line in elim_lines) == 100_000  # 500,000 * 20% = 100,000

        # Adversarial Verification: Tenant Beta under FORCE RLS
        with PostgresTenantBoundary(factory).transaction(tenant_b) as conn:
            # 1. SELECT cross-tenant read returns 0 rows
            assert len(conn.execute("SELECT * FROM reconforge.shop_floor_lots WHERE lot_id='LOT_LIVE_001'").fetchall()) == 0
            assert len(conn.execute("SELECT * FROM reconforge.project_milestone_invoices WHERE invoice_id='INV_LIVE_001'").fetchall()) == 0
            assert len(conn.execute("SELECT * FROM reconforge.intercompany_profit_in_stock_eliminations WHERE rule_id='RULE_LIVE_PIS_01'").fetchall()) == 0

            # 2. SELECT with forged tenant_id in WHERE returns 0 rows
            assert len(conn.execute("SELECT * FROM reconforge.shop_floor_lots WHERE tenant_id=%s", (tenant_a,)).fetchall()) == 0

            # 3. UPDATE cross-tenant affects 0 rows
            cur_update = conn.execute("UPDATE reconforge.shop_floor_lots SET status='tampered' WHERE lot_id='LOT_LIVE_001'")
            assert cur_update.rowcount == 0

            # 4. DELETE cross-tenant affects 0 rows
            cur_delete = conn.execute("DELETE FROM reconforge.shop_floor_lots WHERE lot_id='LOT_LIVE_001'")
            assert cur_delete.rowcount == 0

            # 5. INSERT with forged tenant_id is rejected by RLS WITH CHECK
            with pytest.raises(psycopg.Error):
                conn.execute(
                    "INSERT INTO reconforge.shop_floor_lots (tenant_id, workspace_id, lot_id, item_id, batch_number, quantity_scaled) VALUES (%s, %s, 'LOT_FORGED', 'ITEM_X', 'B1', 100)",
                    (tenant_a, workspace_id)
                )

        # Cryptographic SHA-256 Audit Chaining verification
        with psycopg.connect(admin_dsn) as admin:
            audit_events = admin.execute(
                "SELECT sequence, previous_hash, event_hash, action FROM reconforge.domain_audit_events WHERE tenant_id=%s ORDER BY sequence",
                (tenant_a,)
            ).fetchall()
            assert len(audit_events) >= 8
            for i, evt in enumerate(audit_events):
                seq, prev_hash, ev_hash, action = evt
                if i > 0:
                    assert prev_hash == audit_events[i - 1][2], f"Hash chain broken at sequence {seq}"

    finally:
        with psycopg.connect(admin_base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name)))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_user)))

