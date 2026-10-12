"""Actual Studio landed costs with independent native FIFO, AP and cash oracle."""
from decimal import Decimal
from typing import Any

from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from tests.erp_expansion_browser_seed import seed_expansion_browser
from tests.gfo_browser_restore import require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

LANDED_COST_BROWSER_TABLES = (
    "procurement_partial_orders", "procurement_partial_order_lines", "procurement_partial_receipts",
    "procurement_partial_invoices", "procurement_partial_invoice_lines", "procurement_partial_commands",
    "ap_purchase_orders", "ap_purchase_order_lines", "ap_goods_receipts", "ap_goods_receipt_lines",
    "ap_supplier_invoices", "ap_supplier_invoice_lines", "ap_three_way_matches", "ap_payment_links",
    "operational_finance_plans", "operational_finance_reviews", "operational_finance_links", "operational_finance_commands",
    "financial_installment_plans", "financial_installment_reviews", "financial_installment_links", "financial_installment_commands",
    "landed_cost_plans", "landed_cost_allocations", "landed_cost_reviews", "landed_cost_links", "landed_cost_commands", "landed_cost_cancellations",
)


def seed_landed_cost_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_expansion_browser(admin_dsn, app_dsn)
    with runtime.actor("browser-maker") as (connection, _, _):
        inventory = PostgresInventoryCoreRepository(connection, runtime.tenant)
        inventory.upsert_uom(uom_code="KG", name="Kilograms", decimal_places=2, category="Weight", workspace="work")
        inventory.upsert_item(item_code="WEIGHT", name="Synthetic weighted product", organization_code="ORG", uom_code="KG",
            inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_warehouse(warehouse_code="NORTH", name="Synthetic north warehouse", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="NORTH", location_code="STOCK", name="Synthetic north receiving", organization_code="ORG", workspace="work")
        require(connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0,
            "Browser procurement starts without synthetic business postings.")
    return runtime


def verify_landed_cost_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, actor):
        orders = connection.execute("SELECT id FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND number='BROWSER-LANDED'",
            (runtime.tenant,)).fetchall()
        require(len(orders) == 1, "Exactly one retained multiline browser owner is required.")
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        view = repository.get(orders[0]["id"], actor=actor)
        require(view["order"]["multiline"] and view["order"]["line_count"] == 2 and view["order"]["row_version"] == 21,
            "Actual multiline parent phases differ.")
        require(view["totals"] == {"ordered_quantity": "0", "reserved_receipt_quantity": "0", "received_quantity": "0", "invoiced_quantity": "0",
            "received_minor": "17000", "accrued_minor": "17000", "paid_minor": "17000", "outstanding_minor": "0"}, "Full exact payable totals differ.")
        require([(line["item_code"], line["uom_code"], line["location_code"], Decimal(line["received_quantity"]), Decimal(line["invoiced_quantity"]))
            for line in view["lines"]] == [("ITEM", "EA", "MAIN/STOCK", Decimal("10"), Decimal("10")), ("WEIGHT", "KG", "NORTH/STOCK", Decimal("2.50"), Decimal("2.50"))],
            "Actual mixed units, warehouse attribution or per-line quantities differ.")
        require(len(view["receipts"]) == 4 and all(receipt["stage"] == "Posted" for receipt in view["receipts"][2:])
            and all(receipt["stage"] == "Prepared" and receipt.get("cancellation_plan_id") for receipt in view["receipts"][:2]),
            "Two cancelled retained drafts and two actual capitalized stock receipts are required.")
        require(len(view["invoices"]) == 2 and [invoice["total_minor"] for invoice in view["invoices"]] == ["5600", "11400"]
            and all(invoice["quantity_text"] is None and len(invoice["lines"]) == 2 and invoice["native_status"] == "Paid" for invoice in view["invoices"]),
            "Two actual native multiline invoices must be accrued and settled.")
        effects = {invoice["accrual_effect_id"] for invoice in view["invoices"]}
        for invoice in view["invoices"]:
            plans = repository.payment_page(view["order"]["id"], invoice["id"], actor=actor)
            require(plans["next_after"] is None and len(plans["records"]) == 2 and all(plan["phase"] == 2 for plan in plans["records"]),
                "Every native invoice requires two independently reviewed posted partial payments.")
            effects.update(plan["posting_effect_id"] for plan in plans["records"])
        native = connection.execute("""SELECT l.posting_effect_id FROM reconforge.inventory_receipt_links l
            JOIN reconforge.procurement_partial_receipts r ON r.tenant_id=l.tenant_id AND r.receipt_plan_id=l.plan_id
            WHERE r.tenant_id=%s AND r.order_id=%s""", (runtime.tenant, view["order"]["id"])).fetchall()
        effects.update(row["posting_effect_id"] for row in native)
        from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
        bundles = PostgresLandedCostRepository(connection, runtime.tenant).list_for_order(view["order"]["id"], actor=actor)
        require(bundles["next_after"] is None and len(bundles["records"]) == 2, "One cancelled draft and one retained paid-charge source are required.")
        cancelled = [bundle for bundle in bundles["records"] if bundle["status"] == "Cancelled"]
        require(len(cancelled) == 1 and cancelled[0]["phase"] == 0 and cancelled[0]["posting_effect_id"] is None,
            "Cancelled browser receiving must retain its original unreceived draft without cash GL.")
        require(cancelled[0]["cancellation"]["actor_id"] != cancelled[0]["preparer_actor_id"], "Cancellation needs independent human evidence.")
        bundle = next(bundle for bundle in bundles["records"] if bundle["status"] == "Posted")
        require(bundle["phase"] == 2 and bundle["freight_minor"] == "777" and bundle["duty_minor"] == "224", "Paid-charge source does not reproduce independently expected exact amounts.")
        require(len({bundle["preparer_actor_id"],bundle["reviewer_actor_id"],bundle["posted_actor_id"]}) == 3, "Three independent humans are required.")
        require(sorted((a["base_minor"],a["freight_minor"],a["duty_minor"]) for a in bundle["allocations"]) == [("12000","548","158"),("5000","229","66")], "Independent Hamilton allocation differs.")
        effects.add(bundle["posting_effect_id"])
        require(len(effects) == 9 and None not in effects, "Exactly nine source-bound native effects are required.")
        totals = connection.execute("""SELECT count(DISTINCT e.id),sum((l->>'debit_minor')::numeric),sum((l->>'credit_minor')::numeric)
            FROM reconforge.finance_posting_effects e CROSS JOIN LATERAL jsonb_array_elements(e.snapshot_json->'lines') l
            WHERE e.tenant_id=%s AND e.id=ANY(%s)""", (runtime.tenant, sorted(effects))).fetchone()
        require(tuple(totals) == (9, 53002, 53002), "Independent expected financial turnover differs from actual immutable GL.")
        layers = connection.execute("""SELECT i.item_code,sum(c.original_quantity_scaled) quantity,sum(c.original_value_minor) value
            FROM reconforge.inventory_cost_layers c JOIN reconforge.inventory_receipt_links l ON l.tenant_id=c.tenant_id AND l.cost_layer_id=c.id
            JOIN reconforge.procurement_partial_receipts r ON r.tenant_id=l.tenant_id AND r.receipt_plan_id=l.plan_id
            JOIN reconforge.inventory_items i ON i.tenant_id=c.tenant_id AND i.id=c.item_id
            WHERE r.tenant_id=%s AND r.order_id=%s GROUP BY i.item_code ORDER BY i.item_code""", (runtime.tenant, view["order"]["id"])).fetchall()
        require([dict(row) for row in layers] == [{"item_code": "ITEM", "quantity": 10, "value": 12706}, {"item_code": "WEIGHT", "quantity": 250, "value": 5295}],
            "Original FIFO quantities and cost do not reproduce the two charged native receipts.")
        return {"order_id": view["order"]["id"], "native_order_id": view["order"]["purchase_order_id"], "line_count": 2,
            "warehouses": ["MAIN/STOCK", "NORTH/STOCK"], "units": ["EA", "KG"], "stock_receipts": 2, "cancelled_bundles": 1, "cancelled_receipt_drafts": 2, "supplier_invoices": 2,
            "payment_installments": 4, "posting_effects": 9, "expected_turnover_minor": "53002", "capitalized_cost_minor": "18001", "paid_charge_minor": "1001", "paid_minor": "17000", "outstanding_minor": "0"}
