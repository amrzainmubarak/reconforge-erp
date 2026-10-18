"""Persisted-human HTTPS API contract for native partial commercial operations."""
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_sales_owner_closure import authenticated_headers
from tests.test_postgres_stock_sales import stock_runtime

_ = receipt_database, stock_runtime


def test_https_commercial_order_partial_native_cash_and_current_identity_permissions(receipt_database: tuple[str, str], stock_runtime: object, tmp_path: Path) -> None:
    from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
    assert isinstance(stock_runtime, ReceiptRuntime)
    runtime = stock_runtime
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=receipt_database[1],
        postgres_require_tls=False, secure_transport=True, policy_cache_enabled=True)
    assert app.openapi()["paths"]["/api/v1/stock-sales/commerce/orders"]
    with TestClient(app, base_url="https://testserver") as client:
        headers = {actor: authenticated_headers(client, runtime, actor) for actor in ("maker", "checker", "poster")}
        catalog = client.get("/api/v1/stock-sales/commerce/catalog?prefix=ITEM&limit=1", headers=headers["maker"])
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["items"][0]["item_code"] == "ITEM"
        response = client.post("/api/v1/stock-sales/commerce/orders", headers=headers["maker"], json={
            "command_id": "http-commercial-create", "number": "HTTP-COMMERCIAL", "customer_code": "CUSTOMER",
            "customer_reference": "CUSTOMER-PO", "currency_code": "USD", "order_date": "2026-10-09",
            "lines": [{"item_code": "ITEM", "warehouse_code": "MAIN", "location_code": "STOCK", "quantity": "10",
                "unit_price_minor": "5000", "discount_basis_points": 1000, "description": "Commercial physical products"}]})
        assert response.status_code == 201, response.text
        acknowledgement = response.json()
        assert acknowledgement["total_minor"] == "45000"
        assert "lines" not in acknowledgement
        identifier = acknowledgement["id"]
        def operation(name: str, actor: str, **parameters: object) -> dict[str, object]:
            nonlocal acknowledgement
            packet = {"command_id": "http-commerce:" + str(acknowledgement["row_version"]) + ":" + name,
                "expected_version": acknowledgement["row_version"], "reason": "Actual HTTP " + name, **parameters}
            answer = client.post(f"/api/v1/stock-sales/commerce/orders/{identifier}/{name}", headers=headers[actor], json=packet)
            assert answer.status_code == 200, answer.text
            acknowledgement = answer.json()
            return packet
        operation("submit", "maker")
        own_approval = client.post(f"/api/v1/stock-sales/commerce/orders/{identifier}/approve", headers=headers["maker"],
            json={"command_id": "http-refused-own-approval", "expected_version": acknowledgement["row_version"], "reason": "Own terms"})
        assert own_approval.status_code == 403, own_approval.text
        operation("approve", "checker")
        operation("open-tranche", "maker", line_number=1, quantity="3")
        detail = client.get(f"/api/v1/stock-sales/commerce/orders/{identifier}", headers=headers["maker"]).json()
        tranche = detail["lines"][0]["tranches"][0]["id"]
        for name, actor, values in [
            ("approve-tranche", "checker", {}),
            ("prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"}),
            ("review-issue", "checker", {}), ("deliver", "poster", {}),
            ("prepare-invoice", "maker", {"invoice_number": "HTTP-COMMERCIAL-INVOICE", "invoice_date": "2026-10-09", "due_date": "2026-10-31",
                "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"}),
            ("review-invoice", "checker", {}), ("invoice", "poster", {}),
            ("prepare-collection", "maker", {"receipt_number": "HTTP-COMMERCIAL-CASH", "receipt_date": "2026-10-10", "journal_code": "CASH", "period_id": "period", "cash_account_code": "CASH"}),
            ("review-collection", "checker", {}), ("collect", "poster", {}),
        ]:
            if name in {"deliver", "invoice", "collect"}:
                denied = client.post(f"/api/v1/stock-sales/commerce/orders/{identifier}/{name}", headers=headers["checker"], json={
                    "command_id": "http-denied:" + name, "expected_version": acknowledgement["row_version"], "reason": "Reviewer may not post", "tranche_id": tranche})
                assert denied.status_code == 403, denied.text
            packet = operation(name, actor, tranche_id=tranche, parameters=values)
            if name == "collect":
                repeated = client.post(f"/api/v1/stock-sales/commerce/orders/{identifier}/{name}", headers=headers[actor], json=packet)
                assert repeated.status_code == 200, repeated.text
                assert repeated.json() == acknowledgement
        detail_response = client.get(f"/api/v1/stock-sales/commerce/orders/{identifier}", headers=headers["maker"])
        assert detail_response.status_code == 200, detail_response.text
        line = detail_response.json()["lines"][0]
        assert line["delivered_quantity_scaled"] == "3"
        assert line["invoiced_minor"] == line["collected_minor"] == "13500"
        assert line["quantity_scaled"] == "10"
