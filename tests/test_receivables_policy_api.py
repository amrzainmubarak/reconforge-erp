"""Actual authenticated HTTP exposure of retained AR policy and exact amounts."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.platform.common import ensure_workspace
from reconforge.utils.money import CurrencyRegistryContext
from tests.receivables_cash_runtime import synthetic_cash_runtime
from tests.test_receivables_monetary_policy import SNAPSHOT

ROOT = "/api/v1/receivables"
POLICY_KEYS = {
    "schema_version", "status", "currency_code", "precision", "rounding_policy",
    "registry_version", "registry_digest", "policy_digest", "source", "source_url", "published_at",
}


@dataclass
class PolicyApi:
    client: TestClient
    headers: dict[str, dict[str, str]]
    workspace: str
    path: Path | None = None
    admin_dsn: str | None = None
    tenant: str = ""

    @property
    def scope_body(self) -> dict[str, str]:
        if self.path is not None:
            return {"workspace": "default"}
        return {"workspace": self.workspace, "organization_code": "CASHORG", "entity_code": "A"}

    @contextmanager
    def admin(self) -> Iterator[Any]:
        if self.path is not None:
            with closing(connect(self.path)) as connection:
                yield connection
        else:
            import psycopg

            with psycopg.connect(self.admin_dsn) as connection:
                yield connection

    def bind(self, snapshot: dict[str, Any]) -> CurrencyRegistryContext:
        context = CurrencyRegistryContext.from_snapshot(snapshot)
        manifest = context.registry_manifest
        payload = json.dumps(context.snapshot(), sort_keys=True, separators=(",", ":"))
        with self.admin() as connection:
            if self.path is not None:
                workspace_id = ensure_workspace(connection, "default")
                connection.execute("INSERT INTO currency_registry_snapshots(registry_digest,registry_version,snapshot_json,captured_at,captured_by) VALUES(?,?,?,'2026-10-03','synthetic-http') ON CONFLICT DO NOTHING", (manifest.digest, manifest.registry_version, payload))
                connection.execute("INSERT INTO currency_registry_bindings(workspace_id,registry_version,registry_digest,bound_at,bound_by) VALUES(?,?,?,'2026-10-03','synthetic-http') ON CONFLICT(workspace_id) DO UPDATE SET registry_version=excluded.registry_version,registry_digest=excluded.registry_digest", (workspace_id, manifest.registry_version, manifest.digest))
            else:
                for currency, precision in (("JPY", 0), ("KWD", 3)):
                    connection.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,%s,'Synthetic HTTP',%s) ON CONFLICT DO NOTHING", (self.tenant, currency, precision))
                connection.execute("INSERT INTO reconforge.currency_registry_snapshots(tenant_id,registry_digest,registry_version,snapshot_json,captured_by) VALUES(%s,%s,%s,%s,'synthetic-http') ON CONFLICT DO NOTHING", (self.tenant, manifest.digest, manifest.registry_version, payload))
                connection.execute("INSERT INTO reconforge.currency_registry_bindings(tenant_id,workspace_id,registry_version,registry_digest,bound_by) VALUES(%s,%s,%s,%s,'synthetic-http') ON CONFLICT(tenant_id,workspace_id) DO UPDATE SET registry_version=excluded.registry_version,registry_digest=excluded.registry_digest", (self.tenant, self.workspace, manifest.registry_version, manifest.digest))
            connection.commit()
        return context

    def financial_counts(self) -> tuple[int, ...]:
        tables = ("ar_customers", "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations", "ar_idempotency_keys")
        with self.admin() as connection:
            if self.path is not None:
                counts = [connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables]
                counts += [connection.execute("SELECT count(*) FROM audit_events WHERE object_type LIKE 'ar_%'").fetchone()[0], connection.execute("SELECT count(*) FROM outbox_events WHERE event_type LIKE 'ar.%'").fetchone()[0]]
            else:
                counts = [connection.execute(f"SELECT count(*) FROM reconforge.{table} WHERE tenant_id=%s", (self.tenant,)).fetchone()[0] for table in tables]
                counts += [connection.execute("SELECT count(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s AND object_type LIKE 'ar_%%'", (self.tenant,)).fetchone()[0], connection.execute("SELECT count(*) FROM reconforge.outbox_events WHERE tenant_id=%s AND aggregate_type IN ('ar_customer','ar_invoice','ar_receipt')", (self.tenant,)).fetchone()[0]]
        return tuple(counts)

    def post(self, path: str, body: dict[str, Any], *, role: str = "maker") -> dict[str, Any]:
        response = self.client.post(ROOT + path, headers=self.headers[role], json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def get(self, path: str) -> dict[str, Any]:
        response = self.client.get(ROOT + path, headers=self.headers["reader"])
        assert response.status_code == 200, response.text
        return response.json()


def _login(client: TestClient, username: str, password: str, base: dict[str, str]) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", headers=base, json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {**base, "Authorization": "Bearer " + response.json()["access_token"]}


@contextmanager
def _local_http(path: Path) -> Iterator[PolicyApi]:
    with closing(connect(path)) as connection:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Synthetic-HTTP-123")
        auth.create_user(username="maker", password="Synthetic-HTTP-123", role="preparer")
        auth.create_user(username="checker", password="Synthetic-HTTP-123", role="reviewer")
    with TestClient(create_api_app(path)) as client:
        headers = {name: _login(client, name, "Synthetic-HTTP-123", {}) for name in ("maker", "checker")}
        headers["reader"] = headers["checker"]
        yield PolicyApi(client, headers, "default", path=path)


@pytest.fixture(params=("sqlite", "postgres"))
def api(request: Any, tmp_path: Path) -> Iterator[PolicyApi]:
    if request.param == "sqlite":
        path = tmp_path / "policy-api.db"
        run_migrations(path)
        with _local_http(path) as harness:
            yield harness
        return
    if not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN") or not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"):
        pytest.skip("PROD033 API requires disposable live PostgreSQL app/admin profile; review 2026-10-03")
    with synthetic_cash_runtime(target="0099_pg_receivables_policy") as runtime:
        app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=runtime.app_dsn, postgres_require_tls=False, secure_transport=True)
        with TestClient(app, base_url="https://testserver") as client:
            base = {"X-ReconForge-Tenant": "cash-a", "X-ReconForge-Workspace": "cash-work"}
            headers = {role: _login(client, name, runtime.password, base) for role, name in (("maker", "cashier"), ("checker", "checker"), ("reader", "reader"))}
            for role in ("maker", "checker"):
                response = client.post("/api/v1/auth/step-up", headers=headers[role], json={"password": runtime.password})
                assert response.status_code == 200, response.text
            yield PolicyApi(client, headers, "cash-work", admin_dsn=runtime.admin_dsn, tenant="cash-a")


def _profile(api: PolicyApi, currency: str, *, limit: int = 10000) -> dict[str, Any]:
    return {"customer_code": "POLICY-" + currency, "name": "Synthetic policy", "currency_code": currency, "credit_limit_minor": limit, **api.scope_body}


def _invoice(api: PolicyApi, currency: str, *, amount: int = 1234, tax: int = 2) -> dict[str, Any]:
    return {"invoice_number": "POLICY-" + currency, "customer_code": "POLICY-" + currency, "invoice_date": "2026-10-03", "currency_code": currency, "tax_minor": tax, "lines": [{"description": "Synthetic", "quantity": "1", "unit_price_minor": amount, "line_total_minor": amount, "tax_minor": tax}], "idempotency_key": "invoice-" + currency, **api.scope_body}


def _approved(api: PolicyApi, currency: str, *, amount: int = 1234, tax: int = 2, limit: int = 10000) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    customer = api.post("/customers", _profile(api, currency, limit=limit))
    invoice = api.post("/invoices", _invoice(api, currency, amount=amount, tax=tax))
    api.post(f"/invoices/{invoice['id']}/submit", {"expected_version": 1})
    approved = api.post(f"/invoices/{invoice['id']}/approve", {"expected_version": 2}, role="checker")
    return customer, invoice, approved


def _assert_text(record: dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert type(record[field]) is int
        assert record[field + "_text"] == str(record[field])


@pytest.mark.parametrize("currency,precision", [("JPY", 0), ("KWD", 3)])
def test_policy_http_retains_history_replay_and_exact_nested_amounts_after_rebind(api: PolicyApi, currency: str, precision: int) -> None:
    context = api.bind(SNAPSHOT)
    initial_outbox_count = api.financial_counts()[-1]
    customer, invoice, approved = _approved(api, currency)
    body = {"receipt_number": "POLICY-" + currency, "customer_code": "POLICY-" + currency, "receipt_date": "2026-10-03", "currency_code": currency, "amount_minor": 1000, "allocations": [{"invoice_id": invoice["id"], "amount_minor": 500}], "idempotency_key": "receipt-" + currency, **api.scope_body}
    receipt = api.post("/receipts", body)
    # Customer, invoice, submission, approval, and receipt each retain one event.
    assert api.financial_counts()[-1] == initial_outbox_count + 5
    policy = customer["monetary_policy"]
    assert set(policy) == POLICY_KEYS
    assert policy["status"] == "captured" and policy["precision"] == precision
    assert policy["registry_digest"] == context.registry_manifest.digest
    for record in (invoice, approved, receipt):
        assert record["monetary_policy"] == policy
        assert "currency_registry_digest" not in record
    _assert_text(customer, "credit_limit_minor")
    _assert_text(invoice, "subtotal_minor", "tax_minor", "total_minor", "allocated_minor", "outstanding_minor")
    _assert_text(invoice["lines"][0], "unit_price_minor", "tax_minor", "line_total_minor")
    _assert_text(receipt, "amount_minor", "allocated_minor", "unallocated_minor")
    _assert_text(receipt["allocations"][0], "amount_minor")
    changed = deepcopy(SNAPSHOT)
    changed["source"] = "Synthetic replacement evidence source"
    api.bind(changed)
    before = api.financial_counts()
    for kind, record in (("customers", customer), ("invoices", invoice), ("receipts", receipt)):
        assert api.get(f"/{kind}/{record['id']}")["monetary_policy"] == policy
        page = api.get(f"/{kind}")
        assert next(row for row in page[kind] if row["id"] == record["id"])["monetary_policy"] == policy
    assert api.post("/receipts", body) == receipt
    assert api.post("/invoices", _invoice(api, currency)) == invoice
    denied = api.client.post(ROOT + f"/receipts/{receipt['id']}/allocate", headers=api.headers["maker"], json={"invoice_id": invoice["id"], "amount_minor": 1, "expected_version": 1})
    assert denied.status_code == 400 and "policy" in denied.text
    new_invoice = {**_invoice(api, currency), "invoice_number": "AFTER-REBIND", "idempotency_key": "after-rebind"}
    assert api.client.post(ROOT + "/invoices", headers=api.headers["maker"], json=new_invoice).status_code == 400
    assert api.financial_counts() == before
    assert api.get(f"/invoices/{invoice['id']}")["outstanding_minor_text"] == "736"


def test_policy_http_large_integers_and_negative_credit_keep_canonical_text(api: PolicyApi) -> None:
    api.bind(SNAPSHOT)
    amount = 9_007_199_254_740_993
    customer, invoice, _ = _approved(api, "JPY", amount=amount, tax=0, limit=amount)
    assert customer["credit_limit_minor"] == amount and customer["credit_limit_minor_text"] == str(amount)
    assert invoice["total_minor"] == amount and invoice["total_minor_text"] == str(amount)
    api.post("/customers", _profile(api, "JPY", limit=1))
    exposure = api.get("/credit-exposure/POLICY-JPY")
    _assert_text(exposure, "credit_limit_minor", "exposure_minor", "available_credit_minor")
    assert exposure["available_credit_minor"] == 1 - amount
    assert "monetary_policy" not in exposure
    receipt = api.post("/receipts", {"receipt_number": "EXACT-LARGE", "customer_code": "POLICY-JPY", "receipt_date": "2026-10-03", "currency_code": "JPY", "amount_minor": " +" + str(amount) + " ", "allocations": [{"invoice_id": invoice["id"], "amount_minor": str(amount)}], **api.scope_body})
    _assert_text(receipt, "amount_minor", "allocated_minor", "unallocated_minor")
    assert receipt["amount_minor_text"] == str(amount)
    assert receipt["allocations"][0]["amount_minor_text"] == str(amount)
    assert api.get(f"/invoices/{invoice['id']}")["status"] == "Paid"


def test_policy_http_money_coercion_is_rejected_before_financial_effects(api: PolicyApi) -> None:
    api.bind(SNAPSHOT)
    _, invoice, _ = _approved(api, "JPY")
    receipt_body = {"receipt_number": "FOR-ALLOCATION", "customer_code": "POLICY-JPY", "receipt_date": "2026-10-03", "currency_code": "JPY", "amount_minor": 100, **api.scope_body}
    receipt = api.post("/receipts", receipt_body)
    cases = [
        ("/customers", _profile(api, "JPY"), ("credit_limit_minor",)),
        ("/invoices", _invoice(api, "JPY"), ("tax_minor",)),
        *[("/invoices", _invoice(api, "JPY"), ("lines", 0, field)) for field in ("unit_price_minor", "line_total_minor", "tax_minor")],
        ("/receipts", receipt_body, ("amount_minor",)),
        ("/receipts", {**receipt_body, "allocations": [{"invoice_id": invoice["id"], "amount_minor": 1}]}, ("allocations", 0, "amount_minor")),
        (f"/receipts/{receipt['id']}/allocate", {"invoice_id": invoice["id"], "amount_minor": 1, "expected_version": 1}, ("amount_minor",)),
    ]
    before = api.financial_counts()
    assert before[-1] > 0
    for path, original, keys in cases:
        for bad_json in ("true", "false", "1.0", "9007199254740993.0", '"1.0"', '"1e3"', '"' + "9" * 129 + '"'):
            body = deepcopy(original)
            parent = body
            for key in keys[:-1]:
                parent = parent[key]
            parent[keys[-1]] = "__INVALID_MONEY__"
            raw = json.dumps(body).replace('"__INVALID_MONEY__"', bad_json)
            response = api.client.post(ROOT + path, headers={**api.headers["maker"], "Content-Type": "application/json"}, content=raw)
            assert response.status_code == 422, (path, keys, bad_json, response.text)
    assert api.financial_counts() == before


def test_policy_http_authority_is_checked_before_retained_snapshot_lookup(api: PolicyApi, monkeypatch: Any) -> None:
    api.bind(SNAPSHOT)
    customer = api.post("/customers", _profile(api, "JPY"))
    assert api.get("/customers/" + customer["id"])["monetary_policy"]["status"] == "captured"
    calls = []

    def forbidden_lookup(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        raise AssertionError("An unauthorized request reached retained policy lookup")

    monkeypatch.setattr(FinancePolicyStore, "entry", forbidden_lookup)
    assert api.client.get(ROOT + "/customers/" + customer["id"]).status_code == 401
    denied = api.client.post(ROOT + "/customers", headers=api.headers["reader"], json=_profile(api, "JPY"))
    assert denied.status_code == 403
    if api.path is None:
        for narrowed in (
            {"X-ReconForge-Tenant": "cash-b"},
            {"X-ReconForge-Workspace": "cash-other"},
            {"X-ReconForge-Organization": "cash-org", "X-ReconForge-Legal-Entity": "cash-entity-b"},
        ):
            denied = api.client.get(ROOT + "/customers/" + customer["id"], headers={**api.headers["reader"], **narrowed})
            assert denied.status_code in {400, 401, 403}, denied.text
            assert "monetary_policy" not in denied.text and customer["id"] not in denied.text
    assert calls == []


def test_true_pre49_customer_invoice_receipt_remain_unverified_through_http(tmp_path: Path) -> None:
    path = tmp_path / "legacy-policy-api.db"
    run_migrations(path, target_version=48)
    with closing(connect(path)) as connection:
        workspace = ensure_workspace(connection, "default")
        connection.execute("INSERT INTO ar_customers(id,workspace_id,customer_code,name,currency_code,credit_limit_minor,created_at,updated_at) VALUES('old-customer',?,'OLD','Synthetic legacy','KWD',1234,'2026-01-01','2026-01-01')", (workspace,))
        connection.execute("INSERT INTO ar_invoices(id,workspace_id,customer_id,invoice_number,invoice_date,due_date,currency_code,subtotal_minor,tax_minor,total_minor,status,created_at,updated_at) VALUES('old-invoice',?,'old-customer','OLD','2026-01-01','2026-01-01','KWD',1234,0,1234,'Submitted','2026-01-01','2026-01-01')", (workspace,))
        connection.execute("INSERT INTO ar_receipts(id,workspace_id,customer_id,receipt_number,receipt_date,currency_code,amount_minor,status,created_by,posted_by,posted_at,created_at,updated_at) VALUES('old-receipt',?,'old-customer','OLD','2026-01-01','KWD',1234,'Posted','legacy','legacy','2026-01-01','2026-01-01','2026-01-01')", (workspace,))
        connection.commit()
    run_migrations(path)
    with _local_http(path) as api:
        for kind, identifier, amount_field in (("customers", "old-customer", "credit_limit_minor"), ("invoices", "old-invoice", "total_minor"), ("receipts", "old-receipt", "amount_minor")):
            record = api.get(f"/{kind}/{identifier}")
            policy = record["monetary_policy"]
            assert set(policy) == POLICY_KEYS
            assert policy["schema_version"] == 1 and policy["status"] == "unverified" and policy["currency_code"] == "KWD"
            assert all(value is None for key, value in policy.items() if key not in {"schema_version", "status", "currency_code"})
            assert record[amount_field + "_text"] == "1234"
        before = api.financial_counts()
        rejected = api.client.post(ROOT + "/invoices/old-invoice/approve", headers=api.headers["checker"], json={"expected_version": 1})
        assert rejected.status_code == 400
        assert api.financial_counts() == before
