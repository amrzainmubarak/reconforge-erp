"""Independent connected API/FIFO/GL oracle; CRM origin stages remain unqualified."""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.domain.stock_sales import StockOrder
from tests.test_postgres_inventory_receipt_posting import receipt_database  # noqa: F401
from tests.test_postgres_sales_owner_closure import authenticated_headers
from tests.test_postgres_stock_sales import stock_runtime  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Owned synthetic PostgreSQL required; mandatory enterprise cycle gate; review2026-10-26",
)


def test_four_unit_sale_has_independent_fifo_cash_and_balanced_gl(
    receipt_database, stock_runtime, tmp_path: Path,  # noqa: F811
) -> None:
    runtime = stock_runtime
    application = create_api_app(
        tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants",
        postgres_dsn=receipt_database[1], postgres_require_tls=False, secure_transport=True,
    )
    with TestClient(application, base_url="https://testserver") as client:
        humans = {name: authenticated_headers(client, runtime, name) for name in ("maker", "checker", "poster")}
        body = asdict(StockOrder(
            "ENTERPRISE-FOUR", "CUSTOMER", "SYNTHETIC-PO", "ITEM", "MAIN", "STOCK",
            "4", 5000, "USD", "2026-10-09", "Independent four unit journey", 1000,
        ))
        body["unit_price_minor"] = str(body["unit_price_minor"])
        created = client.post("/api/v1/stock-sales/orders", headers=humans["maker"], json={**body, "command_id": "enterprise:create"})
        assert created.status_code == 201, created.text
        order = created.json()
        phases = [
            ("submit", "maker", {}), ("approve", "checker", {}), ("reserve", "maker", {}),
            ("issue/prepare", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"}),
            ("issue/review", "checker", {}), ("deliver", "poster", {}),
            ("invoice/prepare", "maker", {"invoice_number": "ENTERPRISE-INVOICE", "invoice_date": "2026-10-09",
             "due_date": "2026-10-31", "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"}),
            ("invoice/review", "checker", {}), ("invoice/post", "poster", {}),
            ("collection/prepare", "maker", {"receipt_number": "ENTERPRISE-CASH", "receipt_date": "2026-10-10",
             "journal_code": "CASH", "period_id": "period", "cash_account_code": "CASH"}),
            ("collection/review", "checker", {}), ("collection/post", "poster", {}),
        ]
        for phase, human, parameters in phases:
            path = f"/api/v1/stock-sales/orders/{order['id']}/{phase}"
            command = {"command_id": "enterprise:" + phase, "expected_version": order["row_version"], "reason": "Independent enterprise " + phase, **parameters}
            if phase in {"deliver", "invoice/post", "collection/post"}:
                refused = client.post(path, headers=humans["checker"], json=command)
                assert refused.status_code == 403, refused.text
            response = client.post(path, headers=humans[human], json=command)
            assert response.status_code == 200, response.text
            order = response.json()
            if phase == "collection/post":
                # Simulate loss of the committed response: resend byte-equivalent command.
                retry = client.post(path, headers=humans[human], json=command)
                assert retry.status_code == 200 and retry.json() == order
        assert (order["status"], order["total_minor"], order["cogs_minor"]) == ("Paid", "18000", "4800")
    with runtime.actor("poster") as (connection, _receipts, _actor):
        # Hand calculation: receipt10*1200; ship4*1200; sell4*5000 less10%.
        layer = dict(connection.execute(
            "SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s",
            (runtime.tenant,),
        ).fetchone())
        assert layer == {"remaining_quantity_scaled": 6, "remaining_value_minor": 7200}
        balances = connection.execute(
            "SELECT a.account_code,sum(l.debit_minor-l.credit_minor) balance FROM reconforge.finance_entry_lines l "
            "JOIN reconforge.finance_accounts a ON(a.tenant_id=l.tenant_id AND a.id=l.account_id) "
            "JOIN reconforge.finance_posting_effects e ON(e.tenant_id=l.tenant_id AND e.entry_id=l.entry_id) "
            "WHERE l.tenant_id=%s GROUP BY a.account_code",
            (runtime.tenant,),
        ).fetchall()
        actual = {row["account_code"]: int(row["balance"]) for row in balances}
        assert sum(actual.values()) == 0
        assert {code: actual.get(code, 0) for code in ("INVENTORY", "COGS", "REVENUE", "CASH", "AR")} == {
            "INVENTORY": 7200, "COGS": 4800, "REVENUE": -18000, "CASH": 18000, "AR": 0,
        }
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 4
