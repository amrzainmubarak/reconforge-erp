"""End-to-End integration tests for Enterprise v1.0 API modules mounted in create_api_app.

Verifies:
1. Route registration and authorization contract inclusion.
2. Fail-closed 401 unauthenticated security rejection.
3. Authenticated end-to-end execution across:
   - Treasury & Liquidity (/api/v1/treasury)
   - Manufacturing BOM & MRP Netting (/api/v1/manufacturing/bom)
   - HCM Leave & Entitlements (/api/v1/hcm/leave)
   - CRM Contracts & Pipeline (/api/v1/crm/contracts)
"""

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def test_enterprise_routes_registered_and_reject_unauthenticated(tmp_path: Path) -> None:
    db_path = tmp_path / "enterprise_auth.db"
    run_migrations(db_path)
    app = create_api_app(db_path)

    contracts = {(row.method, row.path): row for row in app.state.authorization_contracts}

    # Verify Treasury routes registered
    assert ("GET", "/api/v1/treasury/positions/{bank_account_id}") in contracts
    assert ("POST", "/api/v1/treasury/positions") in contracts
    assert ("POST", "/api/v1/treasury/flows") in contracts
    assert ("POST", "/api/v1/treasury/forecast") in contracts

    # Verify Manufacturing BOM routes registered
    assert ("POST", "/api/v1/manufacturing/bom") in contracts
    assert ("GET", "/api/v1/manufacturing/bom/{item_id}") in contracts
    assert ("POST", "/api/v1/manufacturing/bom/explode") in contracts
    assert ("POST", "/api/v1/manufacturing/bom/net-requirements") in contracts

    # Verify HCM Leave routes registered
    assert ("POST", "/api/v1/hcm/leave/balances") in contracts
    assert ("GET", "/api/v1/hcm/leave/balances/{employee_id}/{leave_type}") in contracts
    assert ("POST", "/api/v1/hcm/leave/requests") in contracts
    assert ("GET", "/api/v1/hcm/leave/requests/{request_id}") in contracts
    assert ("POST", "/api/v1/hcm/leave/requests/{request_id}/approve") in contracts
    assert ("POST", "/api/v1/hcm/leave/requests/{request_id}/cancel") in contracts

    # Verify CRM Contracts routes registered
    assert ("POST", "/api/v1/crm/contracts/opportunities") in contracts
    assert ("GET", "/api/v1/crm/contracts/opportunities/{opportunity_id}") in contracts
    assert ("POST", "/api/v1/crm/contracts/quotations") in contracts
    assert ("POST", "/api/v1/crm/contracts/quotations/{quote_id}/approve") in contracts
    assert ("POST", "/api/v1/crm/contracts/quotations/{quote_id}/convert") in contracts
    assert ("GET", "/api/v1/crm/contracts/contracts/{contract_id}") in contracts

    # Verify unauthenticated requests return 401
    with TestClient(app) as client:
        for method, path in [
            ("GET", "/api/v1/treasury/positions/BA-1"),
            ("GET", "/api/v1/manufacturing/bom/FG-1"),
            ("GET", "/api/v1/hcm/leave/balances/EMP-1/Annual"),
            ("GET", "/api/v1/crm/contracts/opportunities/OPP-1"),
        ]:
            resp = client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} did not reject unauthenticated"
            assert resp.json()["error"]["code"] == "auth_required"


def test_authenticated_enterprise_modules_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "enterprise_e2e.db"
    run_migrations(db_path)

    # Seed admin user and enterprise permissions
    conn = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(conn)
        auth.init_admin(username="admin", password="Secret-Password-123")
        admin_role_id = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()[0]
        enterprise_perms = [
            "manufacturing_execution.read",
            "manufacturing_execution.manage",
            "people_project_payroll.personnel",
            "people_project_payroll.manage",
            "people_project_payroll.approve_time",
            "sales.manage",
            "sales.approve",
        ]
        for perm in enterprise_perms:
            conn.execute(
                "INSERT OR IGNORE INTO permissions (name, description) VALUES (?, ?)",
                (perm, f"Permission {perm}"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_name) VALUES (?, ?)",
                (admin_role_id, perm),
            )
        conn.commit()
    finally:
        conn.close()

    app = create_api_app(db_path)

    with TestClient(app) as client:
        # Authenticate via real login
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Secret-Password-123"},
        )
        assert login_resp.status_code == 200
        token = str(login_resp.json()["access_token"])
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Treasury End-to-End
        pos_resp = client.post(
            "/api/v1/treasury/positions",
            headers=headers,
            json={
                "bank_account_id": "BA-SAR-01",
                "bank_name": "Riyad Bank",
                "currency": "SAR",
                "as_of_date": "2026-11-01",
                "cleared_balance_minor": "100000000",
                "minimum_covenant_minor": "10000000",
            },
        )
        assert pos_resp.status_code == 200
        assert pos_resp.json()["status"] == "success"

        flow_resp = client.post(
            "/api/v1/treasury/flows",
            headers=headers,
            json={
                "flow_id": "FL-001",
                "direction": "inflow",
                "source_type": "receivable",
                "source_reference": "INV-100",
                "currency": "SAR",
                "due_date": "2026-11-05",
                "amount_minor": "50000000",
                "confidence_bps": 9000,
                "status": "projected",
            },
        )
        assert flow_resp.status_code == 200

        forecast_resp = client.post(
            "/api/v1/treasury/forecast",
            headers=headers,
            json={
                "bank_account_id": "BA-SAR-01",
                "horizon_days": 14,
                "bucket_days": 7,
            },
        )
        assert forecast_resp.status_code == 200
        forecast_data = forecast_resp.json()
        assert forecast_data["status"] == "success"
        assert len(forecast_data["buckets"]) >= 1

        # 2. Manufacturing BOM End-to-End
        bom_resp = client.post(
            "/api/v1/manufacturing/bom",
            headers=headers,
            json={
                "bom_id": "BOM-PROD-X",
                "item_id": "PROD-X",
                "revision": "1.0",
                "status": "approved",
                "effective_from": "2026-01-01",
                "effective_to": None,
                "base_quantity": 1,
                "components": [
                    {
                        "line_number": 1,
                        "component_item_id": "STEEL-SHEET",
                        "component_name": "High Tensile Steel Sheet",
                        "component_type": "raw_material",
                        "quantity_per_parent": 2,
                        "scrap_factor_bps": 500,
                        "substitute_item_id": None,
                        "substitute_ratio_bps": 10000,
                    }
                ],
            },
        )
        assert bom_resp.status_code == 200
        assert bom_resp.json()["bom_id"] == "BOM-PROD-X"

        explode_resp = client.post(
            "/api/v1/manufacturing/bom/explode",
            headers=headers,
            json={
                "item_id": "PROD-X",
                "required_quantity": 10,
                "as_of_date": "2026-06-01",
            },
        )
        assert explode_resp.status_code == 200
        lines = explode_resp.json()["exploded_lines"]
        assert len(lines) == 1
        assert lines[0]["item_id"] == "STEEL-SHEET"
        # 10 * 2 = 20 gross, 5% scrap (500 bps) -> +1 scrap -> 21 total
        assert lines[0]["total_required_quantity"] == 21

        # 3. HCM Leave End-to-End
        bal_resp = client.post(
            "/api/v1/hcm/leave/balances",
            headers=headers,
            json={
                "employee_id": "EMP-500",
                "leave_type": "Annual",
                "annual_entitlement_days": 30,
                "accrued_days": 20,
                "consumed_days": 0,
            },
        )
        assert bal_resp.status_code == 200
        assert bal_resp.json()["available_days"] == 20

        # 4. CRM Contracts End-to-End
        opp_resp = client.post(
            "/api/v1/crm/contracts/opportunities",
            headers=headers,
            json={
                "opportunity_id": "OPP-ENTERPRISE-1",
                "organization_id": "org_main",
                "customer_id": "CUST-GLOBAL",
                "title": "Global Deployment",
                "stage": "qualified",
                "estimated_close_date": "2026-12-31",
                "currency": "USD",
                "projected_amount_minor": 20000000,
                "win_probability_bps": 8000,
            },
        )
        assert opp_resp.status_code == 200
        assert opp_resp.json()["weighted_pipeline_value_minor"] == 16000000
