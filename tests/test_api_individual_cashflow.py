from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "individual-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path))


def test_individual_cashflow_api_is_authenticated_and_non_posting(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = {
        "transactions": [
            {"transaction_id": "tx-1", "transaction_date": "2026-07-01", "flow_type": "expense", "category": "food", "amount": "25.00", "reference": "meal-1", "source_reference": "local:tx-1"}
        ],
        "budgets": [
            {"budget_id": "budget-1", "period": "2026-07", "flow_type": "expense", "category": "food", "limit": "20.00", "source_reference": "local:budget-1"}
        ],
        "currency": "USD",
    }
    assert client.post("/api/v1/individual/cashflow-controls/run", json=payload).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post("/api/v1/individual/cashflow-controls/run", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["individual_cashflow"]["status_counts"] == {"over_budget": 1}
    assert body["network_dispatch"] == "disabled"
    assert body["source"] == {"kind": "local-individual-cashflow-control", "server_mode": False}


def test_individual_cashflow_api_rejects_invalid_money_and_record_limits(tmp_path: Path) -> None:
    client = _client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    bad = client.post(
        "/api/v1/individual/cashflow-controls/run",
        json={"transactions": [{"transaction_id": "tx", "transaction_date": "2026-07-01", "flow_type": "expense", "category": "food", "amount": 1.25, "reference": "r", "source_reference": "s"}]},
        headers=headers,
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "individual_cashflow_control_failed"
