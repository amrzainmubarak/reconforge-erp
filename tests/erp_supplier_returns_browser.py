"""Studio-created charged purchases and exact whole original supplier credit oracle."""
from typing import Any

from reconforge.infrastructure.postgres_supplier_returns import PostgresSupplierReturnsRepository
from tests.erp_landed_cost_browser import LANDED_COST_BROWSER_TABLES, seed_landed_cost_browser
from tests.gfo_browser_restore import require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

SUPPLIER_RETURN_BROWSER_TABLES = LANDED_COST_BROWSER_TABLES + (
    "supplier_return_plans", "supplier_return_events", "supplier_return_commands", "ap_supplier_invoice_credits",
)


def seed_supplier_returns_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    return seed_landed_cost_browser(admin_dsn, app_dsn)


def verify_supplier_returns_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, actor):
        rows = connection.execute("SELECT id,order_id FROM reconforge.supplier_return_plans WHERE tenant_id=%s AND number='SR1-BROWSER'", (runtime.tenant,)).fetchall()
        require(len(rows) == 1, "One real Studio native supplier debit is required.")
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        plan = owner.get(rows[0]["id"], actor=actor)
        purchase = owner.purchase.get(rows[0]["order_id"], actor=actor)
        require((plan["status"], plan["credit_minor"], plan["inventory_removed_minor"], plan["charge_expense_minor"], plan["amount_minor"])
            == ("Posted", "12000", "12706", "706", "25412"), "Original merchandise credit and capitalized FIFO Remove differ from independent integer oracle.")
        require(len(plan["posting_effect_ids"]) == 3 and len({plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]}) == 3,
            "Original FIFO Remove, AP inverse and charge expense require three independent native humans.")
        require((purchase["totals"]["received_minor"], purchase["totals"]["accrued_minor"], purchase["totals"]["credited_minor"], purchase["totals"]["paid_minor"], purchase["totals"]["outstanding_minor"])
            == ("17000", "17000", "12000", "5000", "0"), "Retained historical procurement, original supplier credit and remaining merchandise payments differ.")
        require([invoice["native_status"] for invoice in purchase["invoices"]] == ["Credited", "Paid"], "Returned original AP and remaining warehouse invoice states differ.")
        require(len(purchase["receipts"]) == 2 and len(purchase["invoices"]) == 2, "Two original mixed-unit receipts and separate merchandise AP invoices must be retained.")
        require(connection.execute("SELECT sum(remaining_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 5295,
            "Original weighted remaining FIFO layer differs from independent charge allocation oracle.")
        turnover = connection.execute("""SELECT count(DISTINCT f.id),sum((line->>'debit_minor')::numeric),sum((line->>'credit_minor')::numeric)
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') line WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        require(tuple(turnover) == (10, 66414, 66414), "All actual original receipts, paid charges, AP accruals, supplier debit and two payments must match independent turnover.")
        balances = connection.execute("""SELECT a.account_code,sum((line->>'debit_minor')::numeric-(line->>'credit_minor')::numeric) AS amount
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') line
            JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=line->>'account_id' WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        require({row["account_code"]: int(row["amount"]) for row in balances} == {"AP": 0, "CASH": -6001, "CLEARING": 0, "INVENTORY": 5295, "ADJUSTMENT": 706},
            "Supplier return must expense original paid charges without manufacturing a cash refund.")
        return {"order_id": purchase["order"]["id"], "supplier_return_id": plan["id"], "supplier_credit_minor": "12000", "removed_fifo_minor": "12706", "charge_expense_minor": "706",
                "stock_receipts": 2, "supplier_invoices": 2, "payment_installments": 2, "posting_effects": 10, "expected_turnover_minor": "66414", "remaining_inventory_minor": "5295", "cash_change_minor": "-6001"}
