from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _setup(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "payables-api.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="prep", password="Secret-123", role="preparer")
        auth.create_user(username="review", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path))


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_payables_api_enforces_roles_and_runs_three_way_match(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    prep_headers = {"Authorization": f"Bearer {_token(client, 'prep')}"}
    review_headers = {"Authorization": f"Bearer {_token(client, 'review')}"}

    supplier = client.post(
        "/api/v1/payables/suppliers",
        headers=prep_headers,
        json={"supplier_code": "SUP-API", "name": "Synthetic Supplier", "currency_code": "USD"},
    )
    order = client.post(
        "/api/v1/payables/purchase-orders",
        headers=prep_headers,
        json={
            "po_number": "PO-API",
            "supplier_code": "SUP-API",
            "order_date": "2026-07-01",
            "currency_code": "USD",
            "lines": [{"item_code": "ITEM-API", "ordered_quantity": "2", "unit_price_minor": 1_500}],
        },
    )
    order_id = order.json()["id"]
    line_id = order.json()["lines"][0]["id"]
    submit_order = client.post(f"/api/v1/payables/purchase-orders/{order_id}/submit", headers=prep_headers, json={"expected_version": 1})
    approve_order = client.post(f"/api/v1/payables/purchase-orders/{order_id}/approve", headers=review_headers, json={"expected_version": 2})
    receipt = client.post(
        "/api/v1/payables/receipts",
        headers=prep_headers,
        json={
            "receipt_number": "GR-API",
            "purchase_order_id": order_id,
            "receipt_date": "2026-07-03",
            "quantities": {line_id: "2"},
        },
    )
    invoice = client.post(
        "/api/v1/payables/invoices",
        headers=prep_headers,
        json={
            "invoice_number": "INV-API",
            "supplier_code": "SUP-API",
            "invoice_date": "2026-07-04",
            "currency_code": "USD",
            "total_minor": 3_000,
            "purchase_order_id": order_id,
            "lines": [{
                "purchase_order_line_id": line_id,
                "invoiced_quantity": "2",
                "unit_price_minor": 1_500,
                "line_total_minor": 3_000,
            }],
        },
    )
    invoice_id = invoice.json()["id"]
    submit_invoice = client.post(f"/api/v1/payables/invoices/{invoice_id}/submit", headers=prep_headers, json={"expected_version": 1})
    match = client.post(f"/api/v1/payables/invoices/{invoice_id}/match", headers=review_headers)
    approve = client.post(f"/api/v1/payables/invoices/{invoice_id}/approve", headers=review_headers, json={"expected_version": 3})
    denied = client.post(f"/api/v1/payables/purchase-orders/{order_id}/approve", headers=prep_headers, json={"expected_version": 2})

    assert supplier.status_code == 200
    assert order.status_code == 200
    assert submit_order.json()["status"] == "Submitted"
    assert approve_order.json()["status"] == "Approved"
    assert receipt.status_code == 200
    assert invoice.status_code == 200
    assert submit_invoice.json()["status"] == "Submitted"
    assert match.json()["status"] == "Passed"
    assert approve.json()["status"] == "Approved"
    assert denied.status_code == 403
    assert "Traceback" not in denied.text
