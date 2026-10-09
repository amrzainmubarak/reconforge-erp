"""Real selected-scope HTTP product operations with persisted native humans."""

from dataclasses import asdict
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.domain.stock_sales import StockOrder
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_sales_owner_closure import authenticated_headers
from tests.test_postgres_stock_sales import stock_runtime

_ = receipt_database, stock_runtime


def test_https_origin_stock_api_completes_native_issue_invoice_and_cash(
    receipt_database: tuple[str, str], stock_runtime: ReceiptRuntime, tmp_path: Path,
) -> None:
    runtime = stock_runtime
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=receipt_database[1],
                         postgres_require_tls=False, secure_transport=True, policy_cache_enabled=True)
    assert any(getattr(route, "path", "") == "/api/v1/stock-sales/orders" for route in app.routes)
    with TestClient(app, base_url="https://testserver") as client:
        headers_by_actor = {name: authenticated_headers(client, runtime, name) for name in ("maker", "checker", "poster")}
        headers = headers_by_actor["maker"]
        choices = client.get("/api/v1/stock-sales/options", headers=headers)
        assert choices.status_code == 200, choices.text
        assert choices.json()["items"][0]["item_code"] == "ITEM"
        assert choices.json()["policies"][0]["policy_code"] == "FIFO"
        body = asdict(StockOrder("HTTP-PRODUCT", "CUSTOMER", "HTTP-PO-1", "ITEM", "MAIN", "STOCK", "5", 5000,
                                "USD", "2026-10-09", "HTTP physical products", 1000))
        body["unit_price_minor"] = str(body["unit_price_minor"])
        created = client.post("/api/v1/stock-sales/orders", headers=headers, json={**body, "command_id": "http:create"})
        assert created.status_code == 201, created.text
        order = created.json()
        actions = [
            ("submit", "maker", {}), ("approve", "checker", {}), ("reserve", "maker", {}),
            ("issue/prepare", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"}),
            ("issue/review", "checker", {}), ("deliver", "poster", {}),
            ("invoice/prepare", "maker", {"invoice_number": "HTTP-PRODUCT-INVOICE", "invoice_date": "2026-10-09",
                "due_date": "2026-10-31", "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"}),
            ("invoice/review", "checker", {}), ("invoice/post", "poster", {}),
            ("collection/prepare", "maker", {"receipt_number": "HTTP-PRODUCT-CASH", "receipt_date": "2026-10-10",
                "journal_code": "CASH", "period_id": "period", "cash_account_code": "CASH"}),
            ("collection/review", "checker", {}), ("collection/post", "poster", {}),
        ]
        for path, name, parameters in actions:
            headers = headers_by_actor[name]
            response = client.post("/api/v1/stock-sales/orders/" + order["id"] + "/" + path, headers=headers,
                json={"command_id": "http:" + path, "expected_version": order["row_version"], "reason": "Actual HTTP " + path, **parameters})
            assert response.status_code == 200, response.text
            order = response.json()
        assert (order["status"], order["total_minor"], order["cogs_minor"]) == ("Paid", "22500", "6000")
        assert len(order["events"]) == 13
        with runtime.actor("poster") as (connection, _, _actor):
            assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 4
            assert connection.execute("SELECT status FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, order["invoice_id"])).fetchone()["status"] == "Paid"
