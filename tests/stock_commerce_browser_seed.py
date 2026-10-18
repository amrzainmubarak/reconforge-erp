"""Real reviewed opening inventory for the multiwarehouse Studio commercial gate."""

from dataclasses import replace
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_stock_commerce import PostgresStockCommerceRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_browser_restore import require
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, request
from tests.test_postgres_stock_sales import create_stock_runtime


def seed_stock_commerce_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_receipt_browser(admin_dsn, app_dsn)
    create_stock_runtime((admin_dsn, app_dsn), base_runtime=runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
        inventory = PostgresInventoryCoreRepository(connection, runtime.tenant)
        inventory.upsert_item(item_code="ITEM-B", name="Product B", organization_code="ORG", uom_code="EA", inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_warehouse(warehouse_code="SOUTH", name="South distribution", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="SOUTH", location_code="STOCK", name="South stock", organization_code="ORG", workspace="work")
    with runtime.actor("maker") as (_, participant, actor):
        receipt = participant.prepare_receipt(replace(request("BROWSER-INBOUND-SOUTH"), item_code="ITEM-B", location_code="SOUTH/STOCK", posting_date="2026-10-04", quantity="8", total_value_minor=16000), command_id="browser-south-prepare", actor=actor)
    with runtime.actor("checker") as (_, participant, actor):
        review = participant.review(receipt["plan_id"], command_id="browser-south-review", expected_plan_digest=receipt["plan_digest"], reason="Independent opening inventory", actor=actor)
    with runtime.actor("poster") as (_, participant, actor):
        participant.commit(receipt["plan_id"], command_id="browser-south-post", expected_review_digest=review["review_digest"], reason="Post opening inventory", actor=actor)
    seed_erp_browser_principals(runtime)
    return runtime


def verify_stock_commerce_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    """Independent known-data oracle, including native FIFO/AR/Cash/GL effects."""
    with runtime.actor("browser-poster") as (connection, _, actor):
        owner = PostgresStockCommerceRepository(connection, runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY")
        headers = connection.execute("SELECT id FROM reconforge.stock_commerce_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(headers) == 1, "Browser commercial order was lost or duplicated.")
        result = owner.get(headers[0]["id"], actor=actor)
        require(result["number"] == "BROWSER-COMMERCE" and result["row_version"] == 50 and result["total_minor"] == "69000", "Commercial source or command conservation differs.")
        require([line["delivered_quantity_scaled"] for line in result["lines"]] == ["10", "8"], "Actual warehouse deliveries differ from expected quantities.")
        require([line["collected_minor"] for line in result["lines"]] == ["45000", "24000"], "Actual partial commercial collection differs from frozen prices.")
        tranches = [tranche for line in result["lines"] for tranche in line["tranches"]]
        require(len(tranches) == 5 and sum(tranche["status"] == "Paid" for tranche in tranches) == 4 and sum(tranche["status"] == "Cancelled" for tranche in tranches) == 1, "Four reviewed delivery/invoice/cash cycles and one released cancellation must finish.")
        for tranche in (row for row in tranches if row["status"] == "Paid"):
            for kind in ("issue", "invoice", "collection"):
                require(tranche[kind + "_preparer_id"] == "erp-maker" and tranche[kind + "_reviewer_id"] == "erp-checker", "Browser source review provenance changed.")
        residual = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        require(residual["q"] == residual["v"] == 0, "Native FIFO did not deplete exact opening inventory.")
        effects = connection.execute("""SELECT count(*) n,sum(e.total_debit_minor) d,sum(e.total_credit_minor) c
            FROM reconforge.finance_posting_effects p JOIN reconforge.finance_entries e ON e.tenant_id=p.tenant_id AND e.id=p.entry_id WHERE p.tenant_id=%s""", (runtime.tenant,)).fetchone()
        require(effects["n"] == 14 and effects["d"] == effects["c"] == 194000, "GL oracle requires fourteen exact effects and balanced turnover.")
        require(connection.execute("SELECT count(*) n FROM reconforge.ar_invoices WHERE tenant_id=%s AND status='Paid'", (runtime.tenant,)).fetchone()["n"] == 4, "Native customer invoices were not fully settled.")
        totals = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) n FROM reconforge.finance_entry_lines l
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        balances = {row["account_code"]: row["n"] for row in totals}
        require(balances["CASH"] == 69000 and balances["AR"] == 0 and balances["INVENTORY"] == 0 and balances["REVENUE"] == -69000 and balances["COGS"] == 28000, "Native account balances disagree with independent product cost and price arithmetic.")
        return {"commercial_order_id": result["id"], "parent_version": 50, "lines": 2, "warehouses": 2, "delivery_invoice_collection_tranches": 4, "cancelled_undelivered_tranches": 1, "posting_effects": 14,
                "revenue_minor": "69000", "cash_minor": "69000", "cogs_minor": "28000", "fifo_residual_quantity": "0", "fifo_residual_minor": "0", "gl_turnover_minor": "194000"}
