"""End-to-End integration tests for Enterprise v1.0 Level 2 vertical integration Phase 3.

Verifies:
1. Route registration and authorization contracts inclusion across:
   - Consolidated Financial Statements & Classified Cash Flow (/api/v1/finance/consolidated-statements)
   - Master Production Scheduling (MPS) & Sourcing Optimization (/api/v1/manufacturing/mps)
2. Fail-closed 401 unauthenticated security rejection.
3. Authenticated end-to-end execution across both modules with real JWT bearer token.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def test_enterprise_v3_routes_registered_and_reject_unauthenticated(tmp_path: Path) -> None:
    db_path = tmp_path / "enterprise_auth_v3.db"
    run_migrations(db_path)
    app = create_api_app(db_path)

    contracts = {(row.method, row.path): row for row in app.state.authorization_contracts}

    # Verify Consolidated Statements routes
    assert ("POST", "/api/v1/finance/consolidated-statements/generate") in contracts
    assert ("GET", "/api/v1/finance/consolidated-statements/runs") in contracts
    assert ("GET", "/api/v1/finance/consolidated-statements/runs/{run_id}") in contracts

    # Verify Master Production Schedule (MPS) routes
    assert ("POST", "/api/v1/manufacturing/mps/compute") in contracts
    assert ("GET", "/api/v1/manufacturing/mps/plans") in contracts
    assert ("GET", "/api/v1/manufacturing/mps/plans/{plan_id}/{revision}") in contracts
    assert ("GET", "/api/v1/manufacturing/mps/requisitions") in contracts

    # Verify unauthenticated requests return 401
    with TestClient(app) as client:
        for method, path in [
            ("GET", "/api/v1/finance/consolidated-statements/runs"),
            ("GET", "/api/v1/finance/consolidated-statements/runs/csr-123"),
            ("GET", "/api/v1/manufacturing/mps/plans"),
            ("GET", "/api/v1/manufacturing/mps/plans/p1/r1"),
            ("GET", "/api/v1/manufacturing/mps/requisitions"),
        ]:
            resp = client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} expected 401 unauthenticated, got {resp.status_code}"


def test_enterprise_v3_authenticated_end_to_end_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "enterprise_e2e_v3.db"
    run_migrations(db_path)

    conn = connect(db_path, require_exists=True)
    try:
        auth_service = LocalAuthService(conn)
        auth_service.init_admin(username="enterprise_lead_v3", password="EliteMasterPassword2026!")
        admin_role_id = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()[0]
        perms = [
            "finance_core.read",
            "finance_core.manage",
            "manufacturing_supply_plan.read",
            "manufacturing_supply_plan.manage",
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
            json={"username": "enterprise_lead_v3", "password": "EliteMasterPassword2026!"},
        )
        assert login_resp.status_code == 200, login_resp.text
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Test Consolidated Statements Generation
        cons_payload = {
            "group_id": "GRP_ACME",
            "organization_id": "ORG_CORP",
            "reporting_currency": "USD",
            "period_id": "FY2026_Q1",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "as_of_date": "2026-03-31",
            "entities": [
                {
                    "entity_id": "ENT_HOLDING",
                    "functional_currency": "USD",
                    "fx_rate_to_group_scaled": 1_000_000,
                    "parent_ownership_bips": 10_000,
                    "cash_minor": 200_000,
                    "trade_receivables_minor": 150_000,
                    "intercompany_receivables_minor": 50_000,
                    "inventory_minor": 120_000,
                    "ppe_minor": 300_000,
                    "other_assets_minor": 0,
                    "trade_payables_minor": 100_000,
                    "intercompany_payables_minor": 0,
                    "short_term_debt_minor": 50_000,
                    "long_term_debt_minor": 200_000,
                    "other_liabilities_minor": 0,
                    "share_capital_minor": 350_000,
                    "retained_earnings_opening_minor": 50_000,
                    "gross_revenue_minor": 500_000,
                    "intercompany_revenue_minor": 40_000,
                    "cogs_minor": 300_000,
                    "intercompany_cogs_minor": 0,
                    "operating_expenses_minor": 80_000,
                    "depreciation_minor": 20_000,
                    "finance_costs_minor": 10_000,
                    "tax_expense_minor": 20_000,
                },
                {
                    "entity_id": "ENT_GERMANY",
                    "functional_currency": "EUR",
                    "fx_rate_to_group_scaled": 1_100_000,
                    "parent_ownership_bips": 8_000,
                    "cash_minor": 100_000,
                    "trade_receivables_minor": 80_000,
                    "intercompany_receivables_minor": 0,
                    "inventory_minor": 60_000,
                    "ppe_minor": 150_000,
                    "other_assets_minor": 0,
                    "trade_payables_minor": 50_000,
                    "intercompany_payables_minor": 45_455,
                    "short_term_debt_minor": 20_000,
                    "long_term_debt_minor": 100_000,
                    "other_liabilities_minor": 0,
                    "share_capital_minor": 150_000,
                    "retained_earnings_opening_minor": 20_000,
                    "gross_revenue_minor": 300_000,
                    "intercompany_revenue_minor": 0,
                    "cogs_minor": 180_000,
                    "intercompany_cogs_minor": 36_364,
                    "operating_expenses_minor": 50_000,
                    "depreciation_minor": 10_000,
                    "finance_costs_minor": 5_000,
                    "tax_expense_minor": 10_000,
                },
            ],
            "eliminations": {
                "intercompany_receivables_eliminated_minor": 50_000,
                "intercompany_payables_eliminated_minor": 50_000,
                "intercompany_revenue_eliminated_minor": 40_000,
                "intercompany_cogs_eliminated_minor": 40_000,
                "profit_in_stock_eliminated_minor": 5_000,
            },
        }
        cons_resp = client.post(
            "/api/v1/finance/consolidated-statements/generate",
            json=cons_payload,
            headers=headers,
        )
        assert cons_resp.status_code == 200, cons_resp.text
        cons_data = cons_resp.json()
        assert cons_data["status"] == "generated"
        assert cons_data["statements"]["balance_sheet"]["balanced"] is True
        run_id = cons_data["run_id"]

        # Fetch statement run by ID
        fetch_run_resp = client.get(
            f"/api/v1/finance/consolidated-statements/runs/{run_id}",
            headers=headers,
        )
        assert fetch_run_resp.status_code == 200
        assert fetch_run_resp.json()["id"] == run_id

        # 3. Test Master Production Schedule (MPS) Computation
        mps_payload = {
            "plan_id": "MPS_AUTO_01",
            "plan_name": "Automotive Pump Q2 Plan",
            "revision": "1.0.0",
            "item_id": "PUMP_VALVE_01",
            "unit_of_measure": "EA",
            "quantity_scale": 1000,
            "safety_stock_scaled": 20_000,
            "lot_size_multiple_scaled": 10_000,
            "opening_inventory_scaled": 30_000,
            "preferred_supplier_id": "SUPP_VALVES_GLOBAL",
            "unit_price_ceiling_minor": 50_000,
            "currency": "USD",
            "buckets": [
                {
                    "bucket_index": 0,
                    "bucket_start_date": "2026-05-01",
                    "bucket_end_date": "2026-05-07",
                    "sales_orders_scaled": 25_000,
                    "forecast_demand_scaled": 20_000,
                    "scheduled_receipts_scaled": 0,
                },
                {
                    "bucket_index": 1,
                    "bucket_start_date": "2026-05-08",
                    "bucket_end_date": "2026-05-14",
                    "sales_orders_scaled": 15_000,
                    "forecast_demand_scaled": 20_000,
                    "scheduled_receipts_scaled": 0,
                },
            ],
        }
        mps_resp = client.post(
            "/api/v1/manufacturing/mps/compute",
            json=mps_payload,
            headers=headers,
        )
        assert mps_resp.status_code == 200, mps_resp.text
        mps_data = mps_resp.json()
        assert mps_data["status"] == "computed"
        assert mps_data["sourcing_requisitions_count"] > 0

        # List MPS plans
        list_mps_resp = client.get(
            "/api/v1/manufacturing/mps/plans",
            headers=headers,
        )
        assert list_mps_resp.status_code == 200
        assert list_mps_resp.json()["total_count"] >= 1

        # List sourcing requisitions
        list_reqs_resp = client.get(
            "/api/v1/manufacturing/mps/requisitions?plan_id=MPS_AUTO_01",
            headers=headers,
        )
        assert list_reqs_resp.status_code == 200
        reqs = list_reqs_resp.json()["requisitions"]
        assert len(reqs) > 0
        assert reqs[0]["preferred_supplier_id"] == "SUPP_VALVES_GLOBAL"
