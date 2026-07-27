from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _setup(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "receivables-api.db"
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


def test_receivables_api_enforces_roles_and_exposes_credit_and_aging(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    prep_headers = {"Authorization": f"Bearer {_token(client, 'prep')}"}
    review_headers = {"Authorization": f"Bearer {_token(client, 'review')}"}
    customer = client.post(
        "/api/v1/receivables/customers",
        headers=prep_headers,
        json={"customer_code": "CUS-API", "name": "Synthetic Customer", "currency_code": "USD", "credit_limit_minor": 5_000},
    )
    invoice = client.post(
        "/api/v1/receivables/invoices",
        headers=prep_headers,
        json={
            "invoice_number": "AR-API",
            "customer_code": "CUS-API",
            "invoice_date": "2026-07-01",
            "currency_code": "USD",
            "tax_minor": 0,
            "lines": [{"description": "Synthetic sale", "quantity": "2", "unit_price_minor": 1_000, "line_total_minor": 2_000}],
        },
    )
    invoice_id = invoice.json()["id"]
    submit = client.post(f"/api/v1/receivables/invoices/{invoice_id}/submit", headers=prep_headers, json={"expected_version": 1})
    approve = client.post(f"/api/v1/receivables/invoices/{invoice_id}/approve", headers=review_headers, json={"expected_version": 2})
    receipt = client.post(
        "/api/v1/receivables/receipts",
        headers=prep_headers,
        json={
            "receipt_number": "RCPT-API",
            "customer_code": "CUS-API",
            "receipt_date": "2026-07-15",
            "currency_code": "USD",
            "amount_minor": 2_000,
            "allocations": [{"invoice_id": invoice_id, "amount_minor": 2_000}],
        },
    )
    exposure = client.get("/api/v1/receivables/credit-exposure/CUS-API", headers=review_headers)
    aging = client.get("/api/v1/receivables/aging?as_of_date=2026-08-01", headers=review_headers)
    denied = client.post(
        f"/api/v1/receivables/invoices/{invoice_id}/approve",
        headers=prep_headers,
        json={"expected_version": 2},
    )

    assert customer.status_code == 200
    assert invoice.status_code == 200
    assert submit.json()["status"] == "Submitted"
    assert approve.json()["status"] == "Approved"
    assert receipt.status_code == 200
    assert receipt.json()["unallocated_minor"] == 0
    assert exposure.json()["exposure_minor"] == 0
    assert aging.json()["total_outstanding_minor"] == 0
    assert denied.status_code == 403
    assert "Traceback" not in denied.text
