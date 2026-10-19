"""End-to-End integration tests for Enterprise v1.0 Level 2 vertical integration Phase 2.

Verifies:
1. Route registration and authorization contract inclusion across:
   - Intercompany Eliminations & Profit-in-Stock (/api/v1/intercompany/eliminations)
   - Shop Floor Execution & Lot Genealogy (/api/v1/manufacturing/traceability)
   - Project Costing & Milestone Billing (/api/v1/projects/billing)
2. Fail-closed 401 unauthenticated security rejection.
3. Authenticated end-to-end execution across all 3 modules with real JWT bearer token.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def test_enterprise_v2_routes_registered_and_reject_unauthenticated(tmp_path: Path) -> None:
    db_path = tmp_path / "enterprise_auth_v2.db"
    run_migrations(db_path)
    app = create_api_app(db_path)

    contracts = {(row.method, row.path): row for row in app.state.authorization_contracts}

    # Verify Intercompany Elimination routes
    assert ("POST", "/api/v1/intercompany/eliminations/propose") in contracts
    assert ("GET", "/api/v1/intercompany/eliminations/runs") in contracts
    assert ("GET", "/api/v1/intercompany/eliminations/runs/{run_id}") in contracts
    assert ("POST", "/api/v1/intercompany/eliminations/profit-in-stock") in contracts
    assert ("GET", "/api/v1/intercompany/eliminations/profit-in-stock") in contracts

    # Verify Shop Floor Traceability routes
    assert ("POST", "/api/v1/manufacturing/traceability/lots") in contracts
    assert ("GET", "/api/v1/manufacturing/traceability/lots/{lot_id}") in contracts
    assert ("POST", "/api/v1/manufacturing/traceability/dispatch") in contracts
    assert ("GET", "/api/v1/manufacturing/traceability/dispatches/{dispatch_id}") in contracts
    assert ("POST", "/api/v1/manufacturing/traceability/steps/progress") in contracts
    assert ("GET", "/api/v1/manufacturing/traceability/genealogy/backward/{lot_id}") in contracts
    assert ("GET", "/api/v1/manufacturing/traceability/genealogy/forward/{lot_id}") in contracts

    # Verify Project Milestone Billing routes
    assert ("POST", "/api/v1/projects/billing/tasks") in contracts
    assert ("GET", "/api/v1/projects/billing/tasks/{project_id}") in contracts
    assert ("POST", "/api/v1/projects/billing/rate-cards") in contracts
    assert ("POST", "/api/v1/projects/billing/milestones") in contracts
    assert ("GET", "/api/v1/projects/billing/milestones/{milestone_id}") in contracts
    assert ("POST", "/api/v1/projects/billing/milestones/{milestone_id}/verify") in contracts
    assert ("POST", "/api/v1/projects/billing/milestones/{milestone_id}/bill") in contracts
    assert ("POST", "/api/v1/projects/billing/time-logs") in contracts
    assert ("GET", "/api/v1/projects/billing/summary/{project_id}") in contracts

    # Verify unauthenticated requests return 401
    with TestClient(app) as client:
        for method, path in [
            ("GET", "/api/v1/intercompany/eliminations/runs"),
            ("GET", "/api/v1/intercompany/eliminations/profit-in-stock"),
            ("GET", "/api/v1/manufacturing/traceability/lots/L-1"),
            ("GET", "/api/v1/manufacturing/traceability/genealogy/backward/L-1"),
            ("GET", "/api/v1/projects/billing/tasks/P-1"),
            ("GET", "/api/v1/projects/billing/summary/P-1"),
        ]:
            resp = client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} expected 401 unauthenticated, got {resp.status_code}"


def test_enterprise_v2_authenticated_end_to_end_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "enterprise_e2e_v2.db"
    run_migrations(db_path)

    conn = connect(db_path, require_exists=True)
    try:
        auth_service = LocalAuthService(conn)
        auth_service.init_admin(username="enterprise_lead", password="EliteMasterPassword2026!")
        admin_role_id = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()[0]
        perms = [
            "finance_core.read",
            "finance_core.manage",
            "manufacturing_execution.read",
            "manufacturing_execution.manage",
            "project_time_billing.read",
            "project_time_billing.manage",
        ]
        for p in perms:
            conn.execute("INSERT OR IGNORE INTO permissions (name, description) VALUES (?, ?)", (p, f"Permission {p}"))
            conn.execute("INSERT OR IGNORE INTO role_permissions (role_id, permission_name) VALUES (?, ?)", (admin_role_id, p))
        conn.commit()
    finally:
        conn.close()

    app = create_api_app(db_path)

    with TestClient(app) as client:
        # 1. Login to get real JWT access token
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "enterprise_lead", "password": "EliteMasterPassword2026!"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # --- MODULE 1: INTERCOMPANY ELIMINATION & PROFIT-IN-STOCK (Agent A) ---
        digest_a = "1" * 64
        digest_b = "2" * 64
        propose_payload = {
            "reporting_currency": "USD",
            "version": "1.0.0",
            "lines": [
                {
                    "transaction_id": "TX-E2E-1",
                    "period_name": "2026-Q1",
                    "entity_code": "USA_CORP",
                    "counterparty_code": "UK_CORP",
                    "reference": "IC-SETTLE-01",
                    "group_account_code": "IC_REC",
                    "account_type": "Asset",
                    "amount": {"amount": "15000.00", "currency": "USD", "minor_units": 2, "rounding_policy": "ROUND_HALF_UP"},
                    "source_reference": "ref:e2e:1",
                    "source_digest": digest_a,
                },
                {
                    "transaction_id": "TX-E2E-2",
                    "period_name": "2026-Q1",
                    "entity_code": "UK_CORP",
                    "counterparty_code": "USA_CORP",
                    "reference": "IC-SETTLE-01",
                    "group_account_code": "IC_PAY",
                    "account_type": "Liability",
                    "amount": {"amount": "-15000.00", "currency": "USD", "minor_units": 2, "rounding_policy": "ROUND_HALF_UP"},
                    "source_reference": "ref:e2e:2",
                    "source_digest": digest_b,
                },
            ],
        }
        elim_resp = client.post("/api/v1/intercompany/eliminations/propose", json=propose_payload, headers=headers)
        assert elim_resp.status_code == 200, elim_resp.text
        elim_data = elim_resp.json()
        assert elim_data["run_id"].startswith("ICERUN")
        assert len(elim_data["resolutions"]) == 1
        assert elim_data["resolutions"][0]["status"] == "proposed"

        # Test Profit in Stock
        pis_payload = {
            "rule_id": "PIS-E2E-RULE",
            "selling_entity": "SUB_DUBAI",
            "buying_entity": "PARENT_USA",
            "inventory_item_code": "CHIP-SILICON-01",
            "margin_basis_points": 2000,  # 20.00%
            "ending_inventory_cost_minor": 100_000,
            "nci_share_basis_points": 2500,  # 25.00%
            "currency": "USD",
        }
        pis_resp = client.post("/api/v1/intercompany/eliminations/profit-in-stock", json=pis_payload, headers=headers)
        assert pis_resp.status_code == 200, pis_resp.text
        pis_data = pis_resp.json()
        assert pis_data["unrealized_profit_minor"] == 20_000
        assert pis_data["parent_share_minor"] == 15_000
        assert pis_data["nci_share_minor"] == 5_000

        # --- MODULE 2: SHOP FLOOR EXECUTION & LOT GENEALOGY (Agent B) ---
        # Register raw material lot
        raw_lot_resp = client.post(
            "/api/v1/manufacturing/traceability/lots",
            json={
                "lot_id": "LOT-STEEL-E2E",
                "item_id": "STEEL-BAR-10",
                "batch_number": "BATCH-S-01",
                "quantity_scaled": 100_000,
                "scale_factor": 1000,
                "status": "active",
                "notes": "Grade 316 Stainless",
            },
            headers=headers,
        )
        assert raw_lot_resp.status_code == 200, raw_lot_resp.text

        # Register finished lot consuming raw material
        fg_lot_resp = client.post(
            "/api/v1/manufacturing/traceability/lots",
            json={
                "lot_id": "LOT-GEAR-E2E",
                "item_id": "GEAR-ASSEMBLY-01",
                "batch_number": "BATCH-G-01",
                "quantity_scaled": 20_000,
                "scale_factor": 1000,
                "status": "active",
                "notes": "CNC precision ground",
                "parent_lots": [{"parent_lot_id": "LOT-STEEL-E2E", "quantity_consumed_scaled": 40_000}],
            },
            headers=headers,
        )
        assert fg_lot_resp.status_code == 200, fg_lot_resp.text

        # Dispatch work order
        disp_resp = client.post(
            "/api/v1/manufacturing/traceability/dispatch",
            json={
                "dispatch_id": "DISP-E2E-01",
                "work_order_id": "WO-E2E-999",
                "item_id": "GEAR-ASSEMBLY-01",
                "scheduled_quantity_scaled": 20_000,
                "dispatched_lot_id": "LOT-GEAR-E2E",
                "dispatched_at": "2026-10-19T08:30:00Z",
                "steps": [
                    {
                        "step_id": "STEP-E2E-1",
                        "work_order_id": "WO-E2E-999",
                        "operation_sequence": 1,
                        "work_center_id": "WC-CNC-LATHE",
                        "operator_id": "OP-MACHINIST-1",
                        "status": "pending",
                    }
                ],
            },
            headers=headers,
        )
        assert disp_resp.status_code == 200, disp_resp.text

        # Progress step
        step_resp = client.post(
            "/api/v1/manufacturing/traceability/steps/progress",
            json={
                "dispatch_id": "DISP-E2E-01",
                "step": {
                    "step_id": "STEP-E2E-1",
                    "work_order_id": "WO-E2E-999",
                    "operation_sequence": 1,
                    "work_center_id": "WC-CNC-LATHE",
                    "operator_id": "OP-MACHINIST-1",
                    "status": "completed",
                    "actual_run_minutes": 120,
                    "quantity_completed_scaled": 19_500,
                    "quantity_scrapped_scaled": 500,
                    "scrap_reason_code": "CHIP_TOOLING_DEFECT",
                },
            },
            headers=headers,
        )
        assert step_resp.status_code == 200, step_resp.text

        # Test Backward Genealogy
        gene_resp = client.get("/api/v1/manufacturing/traceability/genealogy/backward/LOT-GEAR-E2E", headers=headers)
        assert gene_resp.status_code == 200, gene_resp.text
        gene_data = gene_resp.json()
        assert gene_data["genealogy"]["lot_id"] == "LOT-GEAR-E2E"
        assert len(gene_data["genealogy"]["children"]) == 1
        assert gene_data["genealogy"]["children"][0]["lot_id"] == "LOT-STEEL-E2E"

        # --- MODULE 3: PROJECT COSTING & MILESTONE BILLING (Agent C) ---
        # 1. Create Task
        task_resp = client.post(
            "/api/v1/projects/billing/tasks",
            json={
                "task_id": "TASK-E2E-01",
                "project_id": "PROJ-CORE-ERP",
                "task_code": "WBS.1.0",
                "name": "Phase 1 Foundation",
                "planned_hours": 100,
                "budget_cost_minor": 1_000_000,
                "currency": "USD",
                "status": "in_progress",
            },
            headers=headers,
        )
        assert task_resp.status_code == 200, task_resp.text

        # 2. Register Rate Card
        rc_resp = client.post(
            "/api/v1/projects/billing/rate-cards",
            json={
                "rate_card_id": "RC-PRINCIPAL",
                "project_id": "PROJ-CORE-ERP",
                "resource_role": "Principal Engineer",
                "hourly_cost_rate_minor": 150_00,  # 150.00 USD/hr
                "hourly_bill_rate_minor": 300_00,  # 300.00 USD/hr
                "currency": "USD",
            },
            headers=headers,
        )
        assert rc_resp.status_code == 200, rc_resp.text

        # 3. Log Project Time
        time_resp = client.post(
            "/api/v1/projects/billing/time-logs",
            json={
                "log_id": "LOG-E2E-01",
                "project_id": "PROJ-CORE-ERP",
                "task_id": "TASK-E2E-01",
                "resource_role": "Principal Engineer",
                "hours_worked": 20,
                "log_date": "2026-10-19",
            },
            headers=headers,
        )
        assert time_resp.status_code == 200, time_resp.text
        assert time_resp.json()["actual_cost_minor"] == 3_000_00  # 20 * 150.00
        assert time_resp.json()["billable_amount_minor"] == 6_000_00  # 20 * 300.00

        # 4. Create Milestone
        ms_resp = client.post(
            "/api/v1/projects/billing/milestones",
            json={
                "milestone_id": "MS-E2E-01",
                "project_id": "PROJ-CORE-ERP",
                "contract_line_id": "LINE-AGREEMENT-01",
                "title": "Phase 1 Complete Acceptance",
                "milestone_amount_minor": 10_000_00,  # 10,000.00 USD
                "currency": "USD",
                "due_date": "2026-10-25",
            },
            headers=headers,
        )
        assert ms_resp.status_code == 200, ms_resp.text

        # 5. Verify Milestone
        verify_resp = client.post(
            "/api/v1/projects/billing/milestones/MS-E2E-01/verify",
            json={"verified_at": "2026-10-19T10:00:00Z"},
            headers=headers,
        )
        assert verify_resp.status_code == 200, verify_resp.text

        # 6. Bill Milestone
        bill_resp = client.post(
            "/api/v1/projects/billing/milestones/MS-E2E-01/bill",
            json={
                "customer_code": "CLIENT-GLOBAL-CORP",
                "invoice_id": "INV-E2E-MS-1",
                "issued_at": "2026-10-19T10:30:00Z",
            },
            headers=headers,
        )
        assert bill_resp.status_code == 200, bill_resp.text
        assert bill_resp.json()["billed_amount_minor"] == 10_000_00

        # 7. Summary
        summary_resp = client.get("/api/v1/projects/billing/summary/PROJ-CORE-ERP?currency=USD", headers=headers)
        assert summary_resp.status_code == 200, summary_resp.text
        summary = summary_resp.json()
        assert summary["budget_cost_minor"] == 1_000_000
        assert summary["actual_cost_minor"] == 3_000_00
        assert summary["total_billed_minor"] == 10_000_00
        assert summary["unbilled_wip_minor"] == 0
        # Margin: (10,000 - 3,000) * 10,000 / 10,000 = 7,000 bps (70.00%)
        assert summary["profit_margin_bps"] == 7000
