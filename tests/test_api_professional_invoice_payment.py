from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.professional_invoice_payment_control import (
    run_professional_invoice_payment_control_files,
    verify_professional_invoice_payment_report,
    write_professional_invoice_payment_report,
)
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations

INVOICES = Path("examples/professional_invoice_payment/invoices.json")
PAYMENTS = Path("examples/professional_invoice_payment/payments.json")


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "professional-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path))


def _report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "report.json"
    run = run_professional_invoice_payment_control_files(INVOICES, PAYMENTS, currency="USD", tolerance="0.01")
    write_professional_invoice_payment_report(run, report_path)
    return verify_professional_invoice_payment_report(report_path)


def test_professional_local_api_persists_reads_and_isolates_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path)
    report = _report(tmp_path)
    assert client.post("/api/v1/professional/invoice-payments", json={"report": report}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    payload = {"report": report, "workspace": "firm-a"}
    first = client.post("/api/v1/professional/invoice-payments", json=payload, headers=headers)
    second = client.post("/api/v1/professional/invoice-payments", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["invoice_payment"] == second.json()["invoice_payment"]
    assert first.json()["network_dispatch"] == "disabled"
    digest = str(report["decision_digest"])
    fetched = client.get(
        f"/api/v1/professional/invoice-payments/{digest}", params={"workspace": "firm-a"}, headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["invoice_payment"] == first.json()["invoice_payment"]
    assert client.get(
        f"/api/v1/professional/invoice-payments/{digest}", params={"workspace": "firm-b"}, headers=headers
    ).status_code == 404
    listed = client.get("/api/v1/professional/invoice-payments", params={"workspace": "firm-a"}, headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["invoice_payments"] == [first.json()["invoice_payment"]]


def test_professional_local_api_rejects_tampered_report_and_unknown_digest(tmp_path: Path) -> None:
    client = _client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    tampered = json.loads(json.dumps(_report(tmp_path)))
    tampered["decisions"][0]["reason_code"] = "TAMPERED"
    response = client.post(
        "/api/v1/professional/invoice-payments",
        json={"report": tampered, "workspace": "firm-a"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "professional_invoice_payment_persistence_failed"
    missing = client.get(
        "/api/v1/professional/invoice-payments/" + ("f" * 64),
        params={"workspace": "firm-a"},
        headers=headers,
    )
    assert missing.status_code == 404


def test_professional_api_boundary_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/api/routes/professional_invoice_payment.py" in manifest
    assert "include reconforge/api/server_professional_invoice_payment.py" in manifest
    assert "include reconforge/infrastructure/postgres_professional_invoice_payment.py" in manifest
    assert "include tests/test_api_professional_invoice_payment.py" in manifest
    assert "include tests/test_api_server_professional_invoice_payment.py" in manifest
    assert "include tests/test_postgres_professional_invoice_payment.py" in manifest
