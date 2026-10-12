"""Receipt recovery, request identity, and actual scoped cash authority."""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import connect
from reconforge.io.persisted import encode_financial_idempotency_response
from tests.receivables_cash_runtime import CashRuntime, synthetic_cash_runtime
from tests.test_receivables_api import _setup, _token


def test_local_receipt_read_exact_retry_conflicts_and_legacy_fail_closed(tmp_path: Path) -> None:
    with _setup(tmp_path) as client:
        headers = {"Authorization": f"Bearer {_token(client, 'prep')}"}
        profile = {"customer_code": "CUS-CASH", "name": "Synthetic cash", "currency_code": "USD", "credit_limit_minor": 1000}
        customer = client.post("/api/v1/receivables/customers", headers=headers, json=profile)
        assert customer.status_code == 200
        body = {"receipt_number": "RCPT-RETRY", "customer_code": "CUS-CASH", "receipt_date": "2026-10-03", "currency_code": "USD", "amount_minor": 100, "idempotency_key": "receipt-exact-v1"}
        first = client.post("/api/v1/receivables/receipts", headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert client.post("/api/v1/receivables/receipts", headers=headers, json=body).json() == first.json()
        for changed in ({"amount_minor": 101}, {"receipt_number": "CHANGED"}, {"receipt_date": "2026-10-04"}):
            conflict = client.post("/api/v1/receivables/receipts", headers=headers, json={**body, **changed})
            assert conflict.status_code == 400
        identifier = first.json()["id"]
        assert client.get(f"/api/v1/receivables/receipts/{identifier}", headers=headers).json() == first.json()
        page = client.get("/api/v1/receivables/receipts?limit=1&offset=0", headers=headers).json()
        assert page["pagination"] == {"limit": 1, "offset": 0, "total": 1}
        assert page["receipts"] == [first.json()]
        assert client.get("/api/v1/receivables/receipts?limit=1&offset=1", headers=headers).json()["receipts"] == []
        assert client.get("/api/v1/receivables/receipts?customer_id=missing", headers=headers).json()["pagination"]["total"] == 0
        assert client.get(f"/api/v1/receivables/receipts/{identifier}").status_code == 401
        with connect(tmp_path / "receivables-api.db", require_exists=True) as conn:
            conn.execute("UPDATE ar_idempotency_keys SET response_json=? WHERE idempotency_key=?", (encode_financial_idempotency_response(first.json()).text, body["idempotency_key"]))
            conn.commit()
        legacy = client.post("/api/v1/receivables/receipts", headers=headers, json=body)
        assert legacy.status_code == 400
        assert "identity is unavailable" in legacy.text
        assert client.get(f"/api/v1/receivables/receipts/{identifier}", headers=headers).status_code == 200


@pytest.fixture
def live_cash(tmp_path: Path) -> Iterator[tuple[CashRuntime, TestClient]]:
    if not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN") or not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"):
        pytest.skip("PROD031 live cash contract requires isolated PostgreSQL creation credentials; review 2026-10-10")
    pytest.importorskip("psycopg")
    with synthetic_cash_runtime(target=os.environ.get("RECONFORGE_CASH_TEST_MIGRATION", "head")) as runtime:
        app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=runtime.app_dsn, postgres_require_tls=False, secure_transport=True)
        with TestClient(app, base_url="https://testserver") as client:
            yield runtime, client


def test_live_cash_real_auth_read_scope_request_identity_and_unknown_allocation(live_cash: tuple[CashRuntime, TestClient]) -> None:
    import psycopg

    runtime, client = live_cash
    base = {"X-ReconForge-Tenant": "cash-a", "X-ReconForge-Workspace": "cash-work"}
    login = client.post("/api/v1/auth/browser/login", headers=base, json={"username": "cashier", "password": runtime.password})
    assert login.status_code == 200, login.text
    headers = {**base, "X-ReconForge-CSRF": login.json()["csrf_token"]}
    body = {"receipt_number": "RCT-CASH", "customer_code": "CUS-A", "receipt_date": "2026-10-03", "currency_code": "USD", "amount_minor": 1000, "idempotency_key": "cash-retry"}
    before_auth = client.post("/api/v1/receivables/receipts", headers=headers, json=body)
    assert before_auth.status_code == 403 and before_auth.json()["error"]["code"] == "step_up_required"
    assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
    assert client.post("/api/v1/receivables/receipts", headers=base, json=body).status_code == 403
    posted = client.post("/api/v1/receivables/receipts", headers=headers, json=body)
    assert posted.status_code == 200, posted.text
    receipt_id = posted.json()["id"]
    assert posted.json()["organization_id"] == "cash-org" and posted.json()["legal_entity_id"] == "cash-entity-a"
    for change in ({"organization_code": "CASHORG", "entity_code": "B"}, {"currency_code": "EUR"}):
        rejected = client.post("/api/v1/receivables/receipts", headers=headers, json={**body, "receipt_number": "REJECTED", "idempotency_key": "rejected-key", **change})
        assert rejected.status_code == 400
    assert client.post("/api/v1/receivables/receipts", headers=headers, json=body).json() == posted.json()
    for change in ({"amount_minor": 999}, {"receipt_date": "2026-10-04"}, {"customer_code": "CUS-B"}, {"allocations": [{"invoice_id": runtime.invoice_id, "amount_minor": 1}]}):
        assert client.post("/api/v1/receivables/receipts", headers=headers, json={**body, **change}).status_code == 400
    scoped_a = {**headers, "X-ReconForge-Organization": "cash-org", "X-ReconForge-Legal-Entity": "cash-entity-a"}
    scoped_b = {**headers, "X-ReconForge-Organization": "cash-org", "X-ReconForge-Legal-Entity": "cash-entity-b"}
    # Equal key under a narrower sibling scope never returns the original cache.
    sibling = client.post("/api/v1/receivables/receipts", headers=scoped_b, json={**body, "customer_code": "CUS-B"})
    assert sibling.status_code == 400
    assert receipt_id not in sibling.text
    for denied_headers in (scoped_b, {**headers, "X-ReconForge-Workspace": "cash-other"}, {**headers, "X-ReconForge-Tenant": "cash-b"}):
        denied = client.get(f"/api/v1/receivables/receipts/{receipt_id}", headers=denied_headers)
        assert denied.status_code in {400, 401, 403}
        assert receipt_id not in denied.text
    assert client.get("/api/v1/receivables/receipts", headers=scoped_b).json()["pagination"]["total"] == 0
    listed = client.get("/api/v1/receivables/receipts?limit=1&offset=0", headers=scoped_a)
    assert listed.json()["pagination"]["total"] == 1
    assert listed.json()["receipts"] == [posted.json()]
    allocation = {"invoice_id": runtime.invoice_id, "amount_minor": 400, "expected_version": 1}
    allocated = client.post(f"/api/v1/receivables/receipts/{receipt_id}/allocate", headers=headers, json=allocation)
    assert allocated.status_code == 200, allocated.text
    # Model a lost successful response, followed by exact CAS replay and GET recovery.
    repeated = client.post(f"/api/v1/receivables/receipts/{receipt_id}/allocate", headers=headers, json=allocation)
    assert repeated.status_code == 400
    authoritative = client.get(f"/api/v1/receivables/receipts/{receipt_id}", headers=headers).json()
    assert authoritative["allocated_minor"] == 400 and authoritative["unallocated_minor"] == 600 and authoritative["row_version"] == 2
    assert client.get("/api/v1/receivables/credit-exposure/CUS-A", headers=headers).json()["exposure_minor"] == 976
    for rejected in ({**allocation, "amount_minor": 601, "expected_version": 2}, {**allocation, "invoice_id": "missing", "expected_version": 2}):
        assert client.post(f"/api/v1/receivables/receipts/{receipt_id}/allocate", headers=headers, json=rejected).status_code == 400
    # Historical NULL hierarchy is never guessed or repaired to match an entity invoice.
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("UPDATE reconforge.ar_receipts SET organization_id=NULL,legal_entity_id=NULL WHERE tenant_id='cash-a' AND id=%s", (receipt_id,))
    legacy_allocation = client.post(f"/api/v1/receivables/receipts/{receipt_id}/allocate", headers=headers, json={**allocation, "expected_version": 2})
    assert legacy_allocation.status_code == 400
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("UPDATE reconforge.ar_receipts SET organization_id='cash-org',legal_entity_id='cash-entity-a' WHERE tenant_id='cash-a' AND id=%s", (receipt_id,))
    # Initial creation retries remain original creation responses; GET is current.
    assert client.post("/api/v1/receivables/receipts", headers=headers, json=body).json()["allocated_minor"] == 0
    client.cookies.clear()
    service_headers = {**base, "Authorization": "Bearer " + runtime.service_token}
    for path, payload in (("/api/v1/receivables/receipts", {**body, "receipt_number": "MACHINE", "idempotency_key": "machine"}), (f"/api/v1/receivables/receipts/{receipt_id}/allocate", {**allocation, "expected_version": 2})):
        denied = client.post(path, headers=service_headers, json=payload)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "human_principal_required"
    assert client.get(f"/api/v1/receivables/receipts/{receipt_id}", headers=service_headers).status_code == 200
    draft = client.post("/api/v1/receivables/invoices", headers=service_headers, json={"invoice_number": "SERVICE-DRAFT", "customer_code": "CUS-A", "invoice_date": "2026-10-03", "currency_code": "USD", "lines": [{"description": "Permitted service draft", "quantity": "1", "unit_price_minor": 1, "line_total_minor": 1}]})
    assert draft.status_code == 200, draft.text
    for role, expected in (("reader", 200), ("noaccess", 403)):
        client.cookies.clear()
        login = client.post("/api/v1/auth/browser/login", headers=base, json={"username": role, "password": runtime.password})
        assert login.status_code == 200
        assert client.get(f"/api/v1/receivables/receipts/{receipt_id}", headers=base).status_code == expected
        for kind, identifier in (("customers", runtime.customer_id), ("invoices", runtime.invoice_id)):
            assert client.get(f"/api/v1/receivables/{kind}/{identifier}", headers=base).status_code == expected
            if expected == 200:
                assert client.get(f"/api/v1/receivables/{kind}/{identifier}", headers={**base, "X-ReconForge-Organization": "cash-org", "X-ReconForge-Legal-Entity": "cash-entity-b"}).status_code in {400, 403}
    with psycopg.connect(runtime.admin_dsn) as admin:
        assert admin.execute("SELECT count(*) FROM reconforge.ar_receipts WHERE tenant_id='cash-a'").fetchone()[0] == 1
        assert admin.execute("SELECT amount_minor FROM reconforge.ar_receipt_allocations WHERE tenant_id='cash-a' AND receipt_id=%s", (receipt_id,)).fetchone()[0] == 400
        for table, column in (("domain_audit_events", "action"), ("outbox_events", "event_type")):
            assert admin.execute(f"SELECT count(*) FROM reconforge.{table} WHERE tenant_id='cash-a' AND {column} IN ('ar_receipt_posted','ar_receipt_allocated')").fetchone()[0] == 2
