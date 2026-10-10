"""Original-source credit/refund HTTPS fixture and independent populated-restore oracle."""

from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_returns import PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_browser_restore import require
from tests.test_postgres_customer_returns import create_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

CUSTOMER_RETURN_TABLES = (
    "customer_return_plans", "customer_return_events", "customer_return_commands", "stock_sales_orders",
    "stock_sales_commands", "stock_commerce_orders", "stock_commerce_lines", "stock_commerce_tranches",
    "commercial_collection_plans", "commercial_collection_reviews", "commercial_collection_links", "commercial_collection_commands",
    "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations", "finance_entry_line_dimensions",
)


def seed_customer_returns_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime, _source_id, _invoice_id = create_runtime((admin_dsn, app_dsn), 10000)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    seed_erp_browser_principals(runtime)
    return runtime


def customer_return_browser_source(runtime: ReceiptRuntime) -> str:
    with runtime.actor("browser-maker") as (connection, _, _actor):
        rows = connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND invoice_id IS NOT NULL", (runtime.tenant,)).fetchall()
        require(len(rows) == 1, "Customer return fixture requires one original delivered/invoiced stock source.")
        return str(rows[0]["id"])


def verify_customer_returns_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        plans = connection.execute("SELECT id,operation,phase,amount_minor,invoice_id,payload FROM reconforge.customer_return_plans WHERE tenant_id=%s ORDER BY id", (runtime.tenant,)).fetchall()
        require(len(plans) == 4, "One cancelled original credit, one posted credit and two partial refunds must be retained.")
        require(sum(row["operation"] == "Return" and row["phase"] == 3 for row in plans) == 1, "Reviewed original credit cancellation was lost or duplicated.")
        posted = [row for row in plans if row["operation"] == "Return" and row["phase"] == 2]
        require(len(posted) == 1, "Whole original credit must post once.")
        parent = posted[0]
        require((parent["payload"]["credit_minor"], parent["payload"]["cogs_restored_minor"], parent["payload"]["refund_entitlement_minor"], parent["payload"]["receivable_released_minor"]) == (45000, 12000, 10000, 35000), "Credit differs from independent original price/cost/collection arithmetic.")
        require(sorted(row["amount_minor"] for row in plans if row["operation"] == "Refund" and row["phase"] == 2) == [3000, 7000], "Two actual native partial cash refunds must conserve original collection.")
        for row in plans:
            connection.execute("SELECT reconforge.customer_return_close(%s,%s)", (runtime.tenant, row["id"]))
            plan = owner.get(row["id"], actor=actor)
            require(plan["preparer_actor_id"] == "erp-maker" and plan["reviewer_actor_id"] == "erp-checker", "Browser source governance changed.")
            require((plan["posted_actor_id"] if row["phase"] == 2 else plan["cancelled_actor_id"]) == "erp-poster", "Third browser human native effect or cancellation was lost.")
        invoice = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(parent["invoice_id"])
        require((invoice["status"], invoice["total_minor"], invoice["allocated_minor"], invoice["outstanding_minor"], invoice["refund_due_minor"]) == ("Cancelled", 45000, 10000, 0, 0), "Original invoice history and refund residual must both survive restore.")
        require(connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s AND status='Posted'", (runtime.tenant,)).fetchone()["n"] == 1, "Original received cash history must remain retained once.")
        layer = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        require((layer["q"], layer["v"]) == (10, 12000), "Whole original FIFO cost and quantity restitution differ.")
        require(connection.execute("SELECT count(*) n FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1, "Original immutable FIFO consumption must not be rewritten.")
        require(connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=%s AND effect_type='Restore'", (runtime.tenant,)).fetchone()["n"] == 1, "One original native FIFO restitution must survive restore.")
        totals = connection.execute("""SELECT count(*) n,sum(e.total_debit_minor) d,sum(e.total_credit_minor) c FROM reconforge.finance_posting_effects f
            JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        require((totals["n"], totals["d"], totals["c"]) == (9, 156000, 156000), "Independent nine-effect complete original/refund GL turnover differs.")
        rows = connection.execute("""SELECT a.account_code,sum(l.debit_minor::numeric-l.credit_minor) v FROM reconforge.finance_posting_effects f
            JOIN reconforge.finance_entry_lines l ON l.tenant_id=f.tenant_id AND l.entry_id=f.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        values = {row["account_code"]: row["v"] for row in rows}
        require(all(values[account] == 0 for account in ("AR", "CASH", "REVENUE", "COGS", "REFUND")) and values["INVENTORY"] == 12000 and values["CLEARING"] == -12000, "Native final AR/cash/liability/revenue/COGS/inventory balances disagree with independent oracle.")
        require(connection.execute("SELECT count(*) n FROM reconforge.customer_return_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 12, "Lost responses must retain exactly twelve commands across four governed plans.")
        return {"credit_memo_id": parent["id"], "retained_customer_return_plans": 4, "posted_whole_credits": 1, "cancelled_reviewed_credits": 1,
                "posted_partial_refunds": 2, "original_receipts_retained": 1, "posting_effects": 9, "credit_minor": "45000", "original_collected_minor": "10000",
                "original_receivable_released_minor": "35000", "refund_total_minor": "10000", "refund_due_minor": "0", "restored_original_fifo_quantity": "10",
                "restored_original_fifo_minor": "12000", "retained_original_consumptions": 1, "native_fifo_restitutions": 1, "gl_turnover_minor": "156000"}
