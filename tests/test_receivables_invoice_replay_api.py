"""Actual authenticated HTTP rejects invoice request/source affinity failures."""
from __future__ import annotations

import json
from copy import deepcopy

from tests.test_receivables_monetary_policy import SNAPSHOT
from tests.test_receivables_policy_api import PolicyApi, _invoice, _login, _profile
from tests.test_receivables_policy_api import api as api


def test_authenticated_invoice_retry_checks_request_and_current_scope_before_acknowledgement(api: PolicyApi) -> None:
    api.bind(SNAPSHOT)
    api.post("/customers", _profile(api, "JPY"))
    request = _invoice(api, "JPY")
    original = api.post("/invoices", request)
    before = api.financial_counts()
    assert before[-1] > 0
    for change in ({"invoice_number": "DIFFERENT"}, {"customer_code": "MISSING"}, {"invoice_date": "2026-10-04"},
                   {"due_date": "2026-10-31"}, {"currency_code": "KWD"},
                   {"lines": [{"description": "Different", "quantity": "1", "unit_price_minor": 4321, "line_total_minor": 4321, "tax_minor": 2}]}):
        denied = api.client.post("/api/v1/receivables/invoices", headers=api.headers["maker"], json={**request, **change})
        assert denied.status_code == 400, denied.text
        assert api.financial_counts() == before
    assert api.client.post("/api/v1/receivables/invoices", headers=api.headers["reader"], json=request).status_code == 403
    if api.path is None:
        for narrowing, expected in (({"X-ReconForge-Legal-Entity": "cash-entity-b", "X-ReconForge-Organization": "cash-org"}, 400),
                                    ({"X-ReconForge-Workspace": "missing"}, 403), ({"X-ReconForge-Tenant": "cash-b"}, 401)):
            denied = api.client.post("/api/v1/receivables/invoices", headers={**api.headers["maker"], **narrowing}, json=request)
            assert denied.status_code == expected, denied.text
            assert original["id"] not in denied.text
    assert api.financial_counts() == before
    foreign_scope = {**api.scope_body, **({"entity_code": "B"} if api.path is None else {})}
    api.post("/customers", {**_profile(api, "JPY"), **foreign_scope, "customer_code": "FOREIGN"})
    api.post("/invoices", {**request, **foreign_scope, "invoice_number": "FOREIGN", "customer_code": "FOREIGN", "idempotency_key": "foreign-key"})
    with api.admin() as connection:
        if api.path:
            rows = connection.execute("SELECT idempotency_key,response_json FROM ar_idempotency_keys").fetchall()
        else:
            rows = connection.execute("SELECT idempotency_key,response_json::text FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s", (api.tenant,)).fetchall()
        stored = {row[0]: json.loads(row[1]) for row in rows}
        key = request["idempotency_key"]
        forged = {**stored[key], "response": stored["foreign-key"]["response"]}
        if api.path:
            connection.execute("UPDATE ar_idempotency_keys SET response_json=? WHERE idempotency_key=?", (json.dumps(forged), key))
        else:
            connection.execute("UPDATE reconforge.ar_idempotency_keys SET response_json=%s::jsonb WHERE tenant_id=%s AND idempotency_key=%s", (json.dumps(forged), api.tenant, key))
        connection.commit()
    before = api.financial_counts()
    assert api.client.post("/api/v1/receivables/invoices", headers=api.headers["maker"], json=request).status_code == 400
    if api.path is None:
        narrowed = {**api.headers["maker"], "X-ReconForge-Organization": "cash-org", "X-ReconForge-Legal-Entity": "cash-entity-b"}
        assert api.client.post("/api/v1/receivables/invoices", headers=narrowed, json=request).status_code == 400
    assert api.financial_counts() == before
    with api.admin() as connection:
        if api.path:
            connection.execute("UPDATE ar_idempotency_keys SET response_json=? WHERE idempotency_key=?", (json.dumps(stored[key]), key))
        else:
            connection.execute("UPDATE reconforge.ar_idempotency_keys SET response_json=%s::jsonb WHERE tenant_id=%s AND idempotency_key=%s", (json.dumps(stored[key]), api.tenant, key))
        connection.commit()
    api.post(f"/invoices/{original['id']}/submit", {"expected_version": 1})
    api.post(f"/invoices/{original['id']}/approve", {"expected_version": 2}, role="checker")
    api.post("/receipts", {"receipt_number": "FULL", "customer_code": "POLICY-JPY", "receipt_date": "2026-10-03", "currency_code": "JPY",
                           "amount_minor": original["total_minor"], "allocations": [{"invoice_id": original["id"], "amount_minor": original["total_minor"]}], **api.scope_body})
    api.post("/customers", {**_profile(api, "JPY"), "status": "Suspended", "payment_terms_days": 90})
    changed = deepcopy(SNAPSHOT)
    changed["source"] = "Synthetic replacement"
    api.bind(changed)
    before = api.financial_counts()
    assert api.post("/invoices", request) == original
    current = api.get(f"/invoices/{original['id']}")
    assert current["status"] == "Paid" and current["outstanding_minor_text"] == "0"
    assert original["status"] == "Draft" and original["row_version"] == 1
    assert api.financial_counts() == before
    if api.path:
        other = _login(api.client, "admin", "Synthetic-HTTP-123", {})
    else:
        from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
        from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

        password = "Synthetic-Recovery-123"
        with api.admin() as connection:
            PostgresIdentityRepository(connection).create_user(tenant_id=api.tenant, user_id="recovery-manager", username="recovery-manager", password=password, role_name="cashier")
            for kind, identifier in (("workspace", "cash-work"), ("organization", "cash-org"), ("legal_entity", "cash-entity-a")):
                PostgresScopeAuthorityRepository(connection).grant(tenant_id=api.tenant, grant_id="recovery-" + identifier, principal_type="user", principal_id="recovery-manager", scope_type=kind, scope_id=identifier, actor_id="cash-cashier")
            connection.commit()
        other = _login(api.client, "recovery-manager", password, {"X-ReconForge-Tenant": api.tenant, "X-ReconForge-Workspace": api.workspace})
    recovered = api.client.post("/api/v1/receivables/invoices", headers=other, json=request)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json() == original
    assert api.financial_counts() == before
