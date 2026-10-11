"""Synthetic configuration only; real HTTPS Studio writes every sourcing/budget/AP/GL effect."""
from typing import Any

from reconforge.domain.procurement_sourcing import PERMISSIONS
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_procurement_sourcing import PostgresProcurementSourcingRepository
from tests.erp_procurement_commitments_browser import (
    PROCUREMENT_COMMITMENT_BROWSER_TABLES,
    seed_procurement_commitments_browser,
)
from tests.gfo_browser_restore import require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

PROCUREMENT_SOURCING_BROWSER_TABLES = PROCUREMENT_COMMITMENT_BROWSER_TABLES + (
    "procurement_sourcing_requisitions", "procurement_sourcing_quotes", "procurement_sourcing_events", "procurement_sourcing_commands",
)


def seed_procurement_sourcing_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_procurement_commitments_browser(admin_dsn, app_dsn)
    with runtime.actor("browser-maker") as (connection, _, _):
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        PostgresPayablesRepository(connection, runtime.tenant).upsert_supplier(supplier_code="ALT", name="Synthetic independent alternative supplier",
            currency_code="USD", workspace="work", organization_code="ORG", entity_code="ENTITY")
        for table in ("procurement_sourcing_requisitions", "procurement_sourcing_quotes", "procurement_sourcing_commands"):
            require(connection.execute("SELECT count(*) FROM reconforge." + table + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0,
                "The real browser must retain every source and original quotation.")
    return runtime


def verify_procurement_sourcing_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    from reconforge.domain.budget_control import BudgetScope

    with runtime.actor("browser-poster") as (connection, _, actor):
        rows = connection.execute("SELECT id FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=%s AND number='SRC5-BROWSER'", (runtime.tenant,)).fetchall()
        require(len(rows) == 1, "Exactly one original browser sourcing requisition is required.")
        source = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        detail = source.get(rows[0]["id"], actor=actor)
        head, quotes = detail["head"], detail["quotations"]
        require(head["status"] == "Awarded" and head["row_version"] == 6 and len(quotes) == 2, "Actual original RFQ and two offers must precede the reviewed award.")
        require([(q["payload"]["order"]["supplier_code"], q["payload"]["total_minor"]) for q in quotes] == [("SUP", "17000"), ("ALT", "18000")],
            "Independent original supplier selection differs.")
        require(head["selected_quote_id"] == quotes[0]["id"] and len({head["creator_actor_id"], head["selection_reviewer_actor_id"], head["award_actor_id"]}) == 3,
            "Three distinct persisted humans and deterministic exact winning offer are required.")
        owner = source.commitments.get(head["order_id"], actor=actor)
        purchase = source.purchase.get(head["order_id"], actor=actor)
        budget = source.budgets.get(BudgetScope("work", "org", "entity"), head["budget_id"])
        require((budget["limit_minor"], budget["reserved_minor"], budget["consumed_minor"], budget["available_minor"]) == ("20000", "0", "7400", "12600"),
            "Original appropriation must independently conserve.")
        require((owner["original_minor"], owner["consumed_minor"], owner["released_minor"], owner["remaining_minor"], owner["status"]) == ("17000", "7400", "9600", "0", "Released"),
            "Native original awarded cost and terminal unreceived release differ.")
        require(purchase["order"]["number"] == "BPC1-SRC5-BROWSER" and purchase["order"]["row_version"] == 14,
            "Sourcing must retain the exact original native purchase lifecycle.")
        require(len(purchase["lines"]) == 2 and len(purchase["receipts"]) == 2 and len(purchase["invoices"]) == 1,
            "Two mixed-unit receipts and their native AP source are required.")
        require((purchase["totals"]["received_minor"], purchase["totals"]["accrued_minor"], purchase["totals"]["paid_minor"], purchase["totals"]["outstanding_minor"])
            == ("7400", "7400", "7400", "0"), "Native receipts, AP and two cash settlements differ.")
        require(connection.execute("SELECT sum(remaining_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0]
            == 2 * 1200 + 250 * 2000 // 100, "Independent scaled-integer FIFO oracle differs.")
        require(connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 5,
            "Exactly five original source-owned GL effects are required.")
        require(tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone())
            == (3 * (2 * 1200 + 250 * 2000 // 100),) * 2, "Independent inventory/AP/cash turnover oracle differs.")
        return {"source_id": head["id"], "source_digest": head["source_digest"], "order_id": head["order_id"], "budget_id": head["budget_id"],
            "retained_offers": 2, "selected_supplier": "SUP", "three_independent_humans": True, "original_minor": "17000", "consumed_minor": "7400",
            "released_minor": "9600", "available_minor": "12600", "remaining_inventory_minor": "7400", "posting_effects": 5, "turnover_minor": "22200"}

