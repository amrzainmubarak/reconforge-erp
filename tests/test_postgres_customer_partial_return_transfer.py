"""Actual partial return after governed original-stock warehouse relocation.

This case exercises the historical IT1 owner, the original stock-sale owner and
the new partial-return owner. It does not qualify a new transfer prepared after
CR2 restitution; that current-pool capture has a separate versioned dependency.
"""

from fractions import Fraction

from psycopg import sql

from reconforge.domain.inventory_transfer import TransferPreparation
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from tests.test_postgres_customer_partial_returns import SCOPE, balance, posted, prepare_return
from tests.test_postgres_customer_returns import balances, configure_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_inventory_transfer import TABLES, physical, transfer_runtime
from tests.test_postgres_inventory_transfer import phase as transfer_phase
from tests.test_postgres_stock_sales import create_stock_runtime, execute, repository

_ = receipt_database


def original_rows(runtime: ReceiptRuntime, entry_ids: list[str]) -> dict[str, tuple[str, ...]]:
    """Retain exact historical transfer and original posted finance row texts."""
    with runtime.actor("maker") as (connection, _, _actor):
        result = {
            table: tuple(row["original"] for row in connection.execute(sql.SQL(
                "SELECT to_jsonb(r)::text original FROM reconforge.{} r "
                "WHERE tenant_id=%s ORDER BY to_jsonb(r)::text"
            ).format(sql.Identifier(table)), (runtime.tenant,)))
            for table in TABLES
        }
        for table, predicate in (
            ("finance_entries", "r.id=ANY(%s)"),
            ("finance_entry_lines", "r.entry_id=ANY(%s)"),
            ("finance_posting_effects", "r.entry_id=ANY(%s)"),
            ("finance_entry_line_dimensions", "r.entry_line_id IN(SELECT id FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=ANY(%s))"),
        ):
            parameters = (runtime.tenant, runtime.tenant, entry_ids) if table == "finance_entry_line_dimensions" else (runtime.tenant, entry_ids)
            statement = sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE r.tenant_id=%s AND ").format(sql.Identifier(table))
            result[table] = tuple(row["original"] for row in connection.execute(
                statement + sql.SQL(predicate) + sql.SQL(" ORDER BY to_jsonb(r)::text"), parameters))
        return result


def test_transferred_original_sale_partial_return_preserves_historical_transfer_and_same_fifo_layer(
    receipt_database: tuple[str, str],
) -> None:
    base = transfer_runtime(receipt_database)
    runtime = create_stock_runtime(receipt_database, base_runtime=base, seed_stock=False)
    configure_runtime(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        created = PostgresInventoryTransferRepository(connection, runtime.tenant).create(
            TransferPreparation("CR2-ORIGINAL-RELOCATION", "ITEM", "2", "MAIN/STOCK", "SECOND/STOCK", "period", "2026-10-14",
                                "Relocate original approved goods before the customer sale", SCOPE),
            command_id="partial-transfer-create", actor=actor)
    transferred = transfer_phase(runtime, transfer_phase(runtime, created, "review", "checker"), "post", "poster")
    transfer = transferred["source"]
    with runtime.actor("maker") as (connection, _, actor):
        original_transfer = PostgresInventoryTransferRepository(connection, runtime.tenant).get(transfer["id"], actor=actor)
        assert physical(connection, runtime) == {"MAIN/STOCK": 1, "SECOND/STOCK": 2}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        layer_id = connection.execute("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["id"]
        sale = repository(connection, runtime).create(
            StockOrder("CR2-TRANSFERRED-SALE", "CUSTOMER", "TRANSFERRED-ORIGINAL-PO", "ITEM", "SECOND", "STOCK", "2", 5000,
                       "USD", "2026-10-14", "Sale from the actual destination warehouse", 1000),
            command_id="transferred-sale-create", actor=actor)
        sale = repository(connection, runtime).act(sale["id"], "submit", expected_version=1, command_id="transferred-sale-submit",
                                                   reason="Submit destination warehouse sale", parameters={}, actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        sale = repository(connection, runtime).act(sale["id"], "approve", expected_version=2, command_id="transferred-sale-approve",
                                                   reason="Independent destination warehouse sale approval", parameters={}, actor=actor)
    sale = execute(runtime, sale, "reserve", "maker")
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-14", "period_id": "period", "policy_code": "FIFO"})
    sale = execute(runtime, sale, "review-issue", "checker")
    sale = execute(runtime, sale, "deliver", "poster")
    invoice = SalesInvoicePreparation("CR2-TRANSFERRED-INVOICE", "2026-10-14", "2026-10-31", "SALES", "period", "AR", "REVENUE",
                                      "Actual invoice of independently relocated goods").payload()
    invoice.pop("reason")
    sale = execute(runtime, sale, "prepare-invoice", "maker", invoice)
    sale = execute(runtime, sale, "review-invoice", "checker")
    sale = execute(runtime, sale, "invoice", "poster")
    assert (int(sale["total_minor"]), int(sale["cogs_minor"])) == (9000, 2400)
    with runtime.actor("maker") as (connection, _, actor):
        assert physical(connection, runtime) == {"MAIN/STOCK": 1, "SECOND/STOCK": 0}
        assert PostgresInventoryTransferRepository(connection, runtime.tenant).get(transfer["id"], actor=actor) == original_transfer
        entry_ids = [row["entry_id"] for row in connection.execute(
            "SELECT entry_id FROM reconforge.finance_posting_effects WHERE tenant_id=%s ORDER BY entry_id", (runtime.tenant,))]
        assert len(entry_ids) == 3
    before = original_rows(runtime, entry_ids)
    returned = posted(runtime, prepare_return(runtime, sale["id"], 1, command="transferred-partial-prepare"))
    assert (returned["quantity_scaled"], returned["credit_minor"], returned["cogs_restored_minor"],
            returned["receivable_released_minor"], returned["refund_entitlement_delta_minor"]) == (1, 4500, 1200, 4500, 0)
    state = balance(runtime, sale["id"])
    assert (state["history_version"], state["remaining_quantity_scaled"], state["outstanding_minor"], state["refund_due_minor"]) == (1, 1, 4500, 0)
    assert original_rows(runtime, entry_ids) == before
    with runtime.actor("poster") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(transfer["id"], actor=actor) == original_transfer
        assert owner.act(transfer["id"], "post", expected_digest=transfer["source_digest"], expected_version=2,
            command_id=transfer["id"] + "-post", reason="Independent actual post", actor=actor) == transferred
        assert physical(connection, runtime) == {"MAIN/STOCK": 1, "SECOND/STOCK": 1}
        layers = connection.execute("SELECT id,remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        assert len(layers) == 1 and (layers[0]["id"], layers[0]["remaining_quantity_scaled"], layers[0]["remaining_value_minor"]) == (layer_id, 2, 2400)
        restored = connection.execute("SELECT cost_layer_id,quantity_scaled,value_minor,direction FROM reconforge.customer_partial_return_restorations WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, returned["id"])).fetchall()
        assert len(restored) == 1 and (restored[0]["cost_layer_id"], restored[0]["quantity_scaled"], restored[0]["value_minor"], restored[0]["direction"]) == (layer_id, 1, 1200, 1)
        totals = connection.execute("""SELECT count(DISTINCT f.id) effects,count(l.id) lines,
            sum(l.debit_minor)::text debit,sum(l.credit_minor)::text credit
            FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entry_lines l ON(l.tenant_id,l.entry_id)=(f.tenant_id,f.entry_id)
            WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert (totals["effects"], totals["lines"]) == (5, 10)
        assert Fraction(totals["debit"]) == Fraction(totals["credit"]) == 20700
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    values = balances(runtime)
    assert {code: values[code] for code in ("INVENTORY", "CLEARING", "COGS", "AR", "REVENUE")} == {
        "INVENTORY": 2400, "CLEARING": -3600, "COGS": 1200, "AR": 4500, "REVENUE": -4500}
    assert values.get("CASH", 0) == values.get("REFUND", 0) == 0
    assert original_rows(runtime, entry_ids) == before
