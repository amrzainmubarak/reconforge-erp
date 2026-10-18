"""Only master configuration is seeded; budgets and business effects use Studio."""
from decimal import Decimal
from typing import Any

from reconforge.domain.budget_control import BudgetScope
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_procurement_commitments import PostgresProcurementCommitmentRepository
from tests.erp_procurement_enterprise_browser import PROCUREMENT_ENTERPRISE_TABLES, seed_procurement_enterprise_browser
from tests.gfo_browser_restore import require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

PROCUREMENT_COMMITMENT_BROWSER_TABLES = PROCUREMENT_ENTERPRISE_TABLES + (
    "budget_envelopes", "budget_commitment_events", "budget_commands",
    "procurement_commitment_plans", "procurement_commitment_commands",
)


def seed_procurement_commitments_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_procurement_enterprise_browser(admin_dsn, app_dsn)
    with runtime.actor("browser-maker") as (connection, _, _):
        identities = PostgresIdentityRepository(connection)
        for permission in ("budget_control.read", "budget_control.manage", "budget_control.approve"):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        require(connection.execute("SELECT count(*) FROM reconforge.budget_envelopes WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0,
            "The real browser must create and independently approve its budget.")
    return runtime


def verify_procurement_commitments_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, actor):
        sources = connection.execute("SELECT id FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND number='BPC1-BROWSER'", (runtime.tenant,)).fetchall()
        require(len(sources) == 1, "Exactly one retained native appropriated purchase is required.")
        owner = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        purchase = owner.purchase.get(sources[0]["id"], actor=actor)
        appropriation = owner.get(sources[0]["id"], actor=actor)
        budget = PostgresBudgetControlRepository(connection, runtime.tenant).get(BudgetScope("work", "org", "entity"), appropriation["budget_id"])
        require((budget["status"], budget["limit_minor"], budget["reserved_minor"], budget["consumed_minor"], budget["available_minor"])
            == ("Approved", "20000", "0", "7400", "12600"), "Independent appropriation conservation differs.")
        require((appropriation["original_minor"], appropriation["consumed_minor"], appropriation["released_minor"], appropriation["remaining_minor"], appropriation["status"])
            == ("17000", "7400", "9600", "0", "Released"), "Retained original purchase and terminal release differ.")
        require(purchase["order"]["row_version"] == 14 and len(purchase["lines"]) == 2 and len(purchase["receipts"]) == 2 and len(purchase["invoices"]) == 1,
            "Actual native operation phases and source memberships differ.")
        require([(line["uom_code"], Decimal(line["received_quantity"]), Decimal(line["invoiced_quantity"])) for line in purchase["lines"]]
            == [("EA", Decimal("2"), Decimal("2")), ("KG", Decimal("2.50"), Decimal("2.50"))], "Native mixed-unit receipt and invoice quantities differ.")
        require((purchase["totals"]["received_minor"], purchase["totals"]["accrued_minor"], purchase["totals"]["paid_minor"], purchase["totals"]["outstanding_minor"])
            == ("7400", "7400", "7400", "0"), "Partial receipt, native AP and original two payments must match.")
        events = connection.execute("SELECT operation,amount_minor FROM reconforge.budget_commitment_events WHERE tenant_id=%s ORDER BY budget_version", (runtime.tenant,)).fetchall()
        require([tuple(event) for event in events] == [("Reserve", 17000), ("Consume", 7400), ("Release", 9600)], "Exact native reserve/consume/release source ledger differs.")
        require(connection.execute("SELECT sum(remaining_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0]
            == 2 * 1200 + 250 * 2000 // 100, "Independent scaled-integer FIFO oracle differs.")
        require(tuple(connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (5,), "Exactly five native receipt/AP/payment effects are required.")
        require(tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone())
            == (22200, 22200), "Independent native turnover oracle differs.")
        return {"order_id": appropriation["order_id"], "budget_id": appropriation["budget_id"], "original_minor": "17000", "consumed_minor": "7400",
                "released_minor": "9600", "available_minor": "12600", "line_count": 2, "stock_receipts": 2, "supplier_invoices": 1,
                "payment_installments": 2, "posting_effects": 5, "expected_turnover_minor": "22200", "remaining_inventory_minor": "7400"}
