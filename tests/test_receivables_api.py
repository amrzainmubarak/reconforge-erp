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


def test_customer_currency_and_inactive_approval_are_rejected_without_overriding_history(tmp_path: Path) -> None:
    with _setup(tmp_path) as client:
        prep = {"Authorization": f"Bearer {_token(client, 'prep')}"}
        controller = {"Authorization": f"Bearer {_token(client, 'admin')}"}
        profile = {"customer_code": "CUS", "name": "Synthetic Customer", "currency_code": "USD", "credit_limit_minor": 1000}
        assert client.post("/api/v1/receivables/customers", headers=prep, json=profile).status_code == 200
        created = client.post("/api/v1/receivables/invoices", headers=prep, json={
            "invoice_number": "INV", "customer_code": "CUS", "invoice_date": "2026-07-01", "currency_code": "USD",
            "lines": [{"description": "Synthetic", "quantity": "1", "unit_price_minor": 600, "line_total_minor": 600}],
        })
        assert created.status_code == 200
        invoice_id = created.json()["id"]
        rejected = client.post("/api/v1/receivables/customers", headers=prep, json={**profile, "currency_code": "EUR"})
        assert rejected.status_code == 400
        assert client.post(f"/api/v1/receivables/invoices/{invoice_id}/submit", headers=prep, json={"expected_version": 1}).status_code == 200
        assert client.post("/api/v1/receivables/customers", headers=prep, json={**profile, "status": "Suspended"}).status_code == 200
        blocked = client.post(f"/api/v1/receivables/invoices/{invoice_id}/approve", headers=controller,
                              json={"expected_version": 2, "credit_override_reason": "Synthetic credit exception"})
        assert blocked.status_code == 400
        assert "Active" in blocked.text
        assert client.post("/api/v1/receivables/customers", headers=prep, json=profile).status_code == 200
        approved = client.post(f"/api/v1/receivables/invoices/{invoice_id}/approve", headers=controller, json={"expected_version": 2})
        assert approved.status_code == 200
        assert approved.json()["currency_code"] == "USD"
        assert approved.json()["row_version"] == 3


def test_grouped_aging_api_keeps_currency_totals_separate(tmp_path: Path) -> None:
    with _setup(tmp_path) as client:
        prep = {"Authorization": f"Bearer {_token(client, 'prep')}"}
        review = {"Authorization": f"Bearer {_token(client, 'review')}"}
        for currency, amount in (("USD", 1200), ("JPY", 700), ("EGP", 3400)):
            code = "CUS-" + currency
            assert client.post("/api/v1/receivables/customers", headers=prep, json={
                "customer_code": code, "name": "Synthetic", "currency_code": currency, "credit_limit_minor": 10000,
            }).status_code == 200
            created = client.post("/api/v1/receivables/invoices", headers=prep, json={
                "invoice_number": currency, "customer_code": code, "invoice_date": "2026-07-01", "currency_code": currency,
                "lines": [{"description": "Synthetic", "quantity": "1", "unit_price_minor": amount, "line_total_minor": amount}],
            })
            assert created.status_code == 200
            invoice_id = created.json()["id"]
            assert client.post(f"/api/v1/receivables/invoices/{invoice_id}/submit", headers=prep, json={"expected_version": 1}).status_code == 200
            assert client.post(f"/api/v1/receivables/invoices/{invoice_id}/approve", headers=review, json={"expected_version": 2}).status_code == 200
        assert client.get("/api/v1/receivables/aging?as_of_date=2026-08-01", headers=review).status_code == 400
        grouped = client.get("/api/v1/receivables/aging-by-currency?as_of_date=2026-08-01", headers=review)
        assert grouped.status_code == 200
        body = grouped.json()
        assert set(body) == {"schema_version", "as_of_date", "currency_groups"}
        assert [(group["currency_code"], group["total_outstanding_minor"]) for group in body["currency_groups"]] == [("EGP", 3400), ("JPY", 700), ("USD", 1200)]
        assert client.get("/api/v1/receivables/aging-by-currency?as_of_date=2026-08-01").status_code == 401


def test_receivables_api_drops_future_storage_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "receivables-projection.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="review", password="Secret-123", role="reviewer")
        connection.execute("ALTER TABLE ar_customers ADD COLUMN unknown_customer_column TEXT")
        connection.execute("ALTER TABLE ar_invoices ADD COLUMN unknown_invoice_column TEXT")
        connection.execute("ALTER TABLE ar_invoice_lines ADD COLUMN unknown_invoice_line_column TEXT")
        connection.execute("ALTER TABLE ar_receipts ADD COLUMN unknown_receipt_column TEXT")
        connection.execute("ALTER TABLE ar_receipt_allocations ADD COLUMN unknown_allocation_column TEXT")
        connection.commit()
    finally:
        connection.close()

    client = TestClient(create_api_app(db_path))
    admin_headers = {"Authorization": f"Bearer {_token(client, 'admin')}"}
    review_headers = {"Authorization": f"Bearer {_token(client, 'review')}"}
    customer = client.post(
        "/api/v1/receivables/customers",
        headers=admin_headers,
        json={"customer_code": "CUS-FUTURE", "name": "Future Customer", "currency_code": "USD", "credit_limit_minor": 1_000},
    )
    invoice = client.post(
        "/api/v1/receivables/invoices",
        headers=admin_headers,
        json={
            "invoice_number": "AR-FUTURE",
            "customer_code": "CUS-FUTURE",
            "invoice_date": "2026-08-26",
            "currency_code": "USD",
            "lines": [{"description": "Future test", "quantity": "1", "unit_price_minor": 100, "line_total_minor": 100}],
        },
    )
    submitted = client.post(
        f"/api/v1/receivables/invoices/{invoice.json()['id']}/submit",
        headers=admin_headers,
        json={"expected_version": 1},
    )
    approved = client.post(
        f"/api/v1/receivables/invoices/{invoice.json()['id']}/approve",
        headers=review_headers,
        json={"expected_version": 2},
    )
    receipt = client.post(
        "/api/v1/receivables/receipts",
        headers=admin_headers,
        json={
            "receipt_number": "RCPT-FUTURE",
            "customer_code": "CUS-FUTURE",
            "receipt_date": "2026-08-26",
            "currency_code": "USD",
            "amount_minor": 100,
            "allocations": [{"invoice_id": invoice.json()["id"], "amount_minor": 100}],
        },
    )
    customers = client.get("/api/v1/receivables/customers", headers=admin_headers)
    invoices = client.get("/api/v1/receivables/invoices", headers=admin_headers)
    exposure = client.get("/api/v1/receivables/credit-exposure/CUS-FUTURE", headers=admin_headers)
    receipt_read = client.get(f"/api/v1/receivables/receipts/{receipt.json()['id']}", headers=admin_headers)
    receipts = client.get("/api/v1/receivables/receipts", headers=admin_headers)
    aging = client.get("/api/v1/receivables/aging?as_of_date=2026-08-26", headers=admin_headers)

    assert customer.status_code == 200, customer.text
    assert invoice.status_code == 200, invoice.text
    assert submitted.status_code == 200, submitted.text
    assert approved.status_code == 200, approved.text
    assert receipt.status_code == 200, receipt.text
    assert customers.status_code == 200, customers.text
    assert invoices.status_code == 200, invoices.text
    assert exposure.status_code == 200, exposure.text
    assert aging.status_code == 200, aging.text
    assert all(
        "unknown_" not in response.text
        for response in (customer, invoice, receipt, customers, invoices, exposure, aging, receipt_read, receipts)
    )
