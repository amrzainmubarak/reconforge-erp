"""Actual governed partial credit/refund operations on ordinary PostgreSQL.

The independent posted-cycle oracle is owned separately. These cases exercise
the real command owner and retained native effects, not synthetic SQL postings.
"""

import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.customer_partial_return_commands import (
    CustomerPartialRefundPreparation,
    CustomerPartialReturnPreparation,
    CustomerPartialReversePreparation,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from tests.customer_partial_return_posted_cycle_oracle import TABLES
from tests.test_postgres_commercial_collections import complete, prepare
from tests.test_postgres_customer_partial_return_source import create_two_layer_source, two_layer_source
from tests.test_postgres_customer_returns import balances, configure_runtime, create_runtime, retained_state
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database
from tests.test_postgres_stock_sales import create_reserved_order, create_stock_runtime, execute
from tests.test_postgres_stock_sales import repository as stock_repository

_ = receipt_database, two_layer_source
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
SETTLEMENT_TABLES = tuple(sorted((*TABLES, "customer_partial_return_allocation_witnesses")))


def create_partial_runtime(database: tuple[str, str], paid: int = 10000, *, quantity: str | None = None) -> tuple[ReceiptRuntime, str, str]:
    return create_runtime(database, paid=paid, quantity=quantity)


def retained_partial_state(runtime: ReceiptRuntime) -> dict[str, Any]:
    from psycopg import sql
    state = {"legacy_rows": retained_state(runtime)}
    with runtime.actor("maker") as (connection, _, _actor):
        names = connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='reconforge' AND table_name LIKE 'customer_partial_return_%' ORDER BY table_name").fetchall()
        for row in names:
            state[row["table_name"]] = tuple(item["original"] for item in connection.execute(
                sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text").format(sql.Identifier(row["table_name"])),
                (runtime.tenant,)).fetchall())
    return state


def create_fractional_partial_runtime(database: tuple[str, str], *, unit_price_minor: int | None = None,
                                      item_type: str = "Stock", quantity: str = "2.5") -> tuple[ReceiptRuntime, str, str]:
    base = create_receipt_runtime(database)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        inventory = PostgresInventoryCoreRepository(connection, base.tenant)
        inventory.upsert_uom(uom_code="FRACTIONAL", name="Exact fractional base unit", decimal_places=3, workspace="work")
        # ITEM has no movement/reference history yet. Configure its base unit
        # through the supported API; the already-referenced EA is unchanged.
        inventory.upsert_item(item_code="ITEM", name="Fractional synthetic item", organization_code="ORG",
                              uom_code="FRACTIONAL", inventory_account_code="INVENTORY", workspace="work", item_type=item_type)
    runtime = create_stock_runtime(database, base_runtime=base)
    configure_runtime(runtime)
    if unit_price_minor is None:
        sale = create_reserved_order(runtime, "FRACTIONAL-ORIGINAL", quantity)
    else:
        with runtime.actor("maker") as (connection, _, actor):
            owner = stock_repository(connection, runtime)
            sale = owner.create(StockOrder("FRACTIONAL-ORIGINAL", "CUSTOMER", "CUSTOMER-PO-1", "ITEM", "MAIN", "STOCK",
                quantity, unit_price_minor, "USD", "2026-10-09", "Existing rounded original merchandise"),
                command_id="rounded-original:create", actor=actor)
        sale = execute(runtime, sale, "submit", "maker")
        sale = execute(runtime, sale, "approve", "checker")
        sale = execute(runtime, sale, "reserve", "maker")
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    sale = execute(runtime, sale, "review-issue", "checker")
    sale = execute(runtime, sale, "deliver", "poster")
    args = SalesInvoicePreparation("FRACTIONAL-INVOICE", "2026-10-09", "2026-10-31", "SALES", "period", "AR", "REVENUE", "Exact original fractional merchandise").payload()
    args.pop("reason")
    sale = execute(runtime, sale, "prepare-invoice", "maker", args)
    sale = execute(runtime, sale, "review-invoice", "checker")
    sale = execute(runtime, sale, "invoice", "poster")
    return runtime, sale["id"], sale["invoice_id"]


def request(source_id: str, quantity_scaled: int, version: int = 0) -> CustomerPartialReturnPreparation:
    return CustomerPartialReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY", source_order_id=source_id,
        quantity_scaled=quantity_scaled, period_id="period", posting_date="2026-10-14", journal_code="CASH",
        refund_liability_account_code="REFUND", cash_account_code="CASH", reason="Actual original partial merchandise credit", expected_history_version=version)


def prepare_return(runtime: ReceiptRuntime, source_id: str, quantity_scaled: int, expected_version: int = 0,
                   command: str = "partial-return-prepare") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant)
        args = request(source_id, quantity_scaled, expected_version)
        result = owner.prepare(args, command_id=command, actor=actor)
        assert owner.prepare(args, command_id=command, actor=actor) == result
        return result


def phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, who: str, command: str | None = None) -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": command or plan["id"] + ":" + operation,
                "reason": "Actual partial credit " + operation, "actor": actor}
        result = getattr(owner, operation)(plan["id"], **args)
        assert getattr(owner, operation)(plan["id"], **args) == result
        return result


def posted(runtime: ReceiptRuntime, plan: dict[str, Any]) -> dict[str, Any]:
    reviewed = phase(runtime, plan, "review", "checker")
    assert reviewed["phase"] == 1
    return phase(runtime, reviewed, "post", "poster")


def prepare_refund(runtime: ReceiptRuntime, parent: dict[str, Any], amount: int, version: int, command: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant)
        request = CustomerPartialRefundPreparation(parent["id"], amount, "period", "2026-10-14", "Exact partial refund installment", version)
        result = owner.prepare_refund(request, command_id=command, actor=actor)
        assert owner.prepare_refund(request, command_id=command, actor=actor) == result
        return result


def prepare_reversal(runtime: ReceiptRuntime, parent: dict[str, Any], version: int, command: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant)
        request = CustomerPartialReversePreparation(parent["id"], "period", "2026-10-14", "Exact governed owned correction", version)
        result = owner.prepare_reversal(request, command_id=command, actor=actor)
        assert owner.prepare_reversal(request, command_id=command, actor=actor) == result
        return result


def balance(runtime: ReceiptRuntime, source_id: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresCustomerPartialReturnsRepository(connection, runtime.tenant).balance(source_id, SCOPE, actor=actor)


def test_two_original_fifo_layers_partial_credit_real_collection_and_two_partial_refunds(
    two_layer_source: tuple[ReceiptRuntime, str, str],
) -> None:
    runtime, source_id, invoice_id = two_layer_source
    before = balance(runtime, source_id)
    assert (before["remaining_quantity_scaled"], before["gross_minor"], before["collected_minor"], before["history_version"]) == (15, 67500, 10000, 0)
    first = prepare_return(runtime, source_id, 12)
    assert (first["credit_minor"], first["cogs_restored_minor"], first["receivable_released_minor"], first["refund_entitlement_delta_minor"]) == (54000, 16000, 54000, 0)
    first = posted(runtime, first)
    assert first["phase"] == 2 and len(first["entries"]) == 2
    state = balance(runtime, source_id)
    assert (state["outstanding_minor"], state["remaining_quantity_scaled"], state["history_version"]) == (3500, 3, 1)
    complete(runtime, prepare(runtime, invoice_id, 3500, "AFTER-PARTIAL-CREDIT"), "AFTER-PARTIAL-CREDIT")
    state = balance(runtime, source_id)
    assert (state["outstanding_minor"], state["collected_minor"], state["history_version"]) == (0, 13500, 2)
    second = posted(runtime, prepare_return(runtime, source_id, 3, 2, "second-partial-prepare"))
    assert (second["credit_minor"], second["cogs_restored_minor"], second["receivable_released_minor"], second["refund_entitlement_delta_minor"]) == (13500, 6000, 0, 13500)
    first_refund = posted(runtime, prepare_refund(runtime, second, 6000, 3, "first-partial-refund"))
    assert balance(runtime, source_id)["refund_due_minor"] == 7500
    second_refund = posted(runtime, prepare_refund(runtime, second, 7500, 4, "second-partial-refund"))
    assert first_refund["phase"] == second_refund["phase"] == 2
    state = balance(runtime, source_id)
    assert (state["refund_due_minor"], state["outstanding_minor"], state["remaining_quantity_scaled"], state["history_version"]) == (0, 0, 0, 5)
    values = balances(runtime)
    assert values["INVENTORY"] == 32000 and values["CLEARING"] == -32000
    assert all(values.get(code, 0) == 0 for code in ("AR", "CASH", "COGS", "REVENUE", "REFUND"))
    with runtime.actor("maker") as (connection, _, _actor):
        totals = connection.execute("""SELECT sum(l.debit_minor)::text debit,sum(l.credit_minor)::text credit
            FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entry_lines l ON(l.tenant_id,l.entry_id)=(f.tenant_id,f.entry_id)
            WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert Fraction(totals["debit"]) == Fraction(totals["credit"]) == 238000
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_history WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 5


def test_cancel_releases_exact_unposted_reservation_without_financial_or_physical_effect(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice = create_partial_runtime(receipt_database)
    prepared = prepare_return(runtime, source_id, 4)
    cancelled = phase(runtime, prepared, "cancel", "checker")
    assert cancelled["phase"] == 3 and all(entry["posting_effect_id"] is None for entry in cancelled["entries"])
    assert balance(runtime, source_id)["history_version"] == 0
    replacement = posted(runtime, prepare_return(runtime, source_id, 4, 0, "replacement-after-cancel"))
    assert replacement["id"] != prepared["id"] and replacement["credit_minor"] == 18000
    assert balance(runtime, source_id)["remaining_quantity_scaled"] == 6


def test_latest_refund_and_return_reversals_preserve_originals_and_reopen_exact_liability(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice = create_partial_runtime(receipt_database)
    returned = posted(runtime, prepare_return(runtime, source_id, 10))
    refunded = posted(runtime, prepare_refund(runtime, returned, 3000, 1, "original-refund"))
    before = retained_partial_state(runtime)
    with pytest.raises(FinancePostingError, match="latest"):
        prepare_reversal(runtime, returned, 2, "cannot-invert-refunded-credit")
    assert retained_partial_state(runtime) == before
    inverse_refund = posted(runtime, prepare_reversal(runtime, refunded, 2, "inverse-owned-refund"))
    assert inverse_refund["operation"] == "ReverseRefund"
    assert balance(runtime, source_id)["refund_due_minor"] == 10000
    inverse_return = posted(runtime, prepare_reversal(runtime, returned, 3, "inverse-owned-return"))
    assert inverse_return["operation"] == "ReverseReturn"
    state = balance(runtime, source_id)
    assert (state["credited_minor"], state["returned_quantity_scaled"], state["outstanding_minor"], state["refund_due_minor"]) == (0, 0, 35000, 0)
    values = balances(runtime)
    assert (values["AR"], values["CASH"], values["COGS"], values["REVENUE"], values.get("REFUND", 0)) == (35000, 10000, 12000, -45000, 0)


def test_stale_history_oversize_return_and_refund_cannot_create_an_extra_business_effect(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice = create_partial_runtime(receipt_database)
    returned = posted(runtime, prepare_return(runtime, source_id, 4))
    before = retained_partial_state(runtime)
    with pytest.raises(FinancePostingError):
        prepare_return(runtime, source_id, 7, 1, "oversized-original-quantity")
    with pytest.raises(FinancePostingError):
        prepare_return(runtime, source_id, 1, 0, "stale-history")
    with pytest.raises(FinancePostingError):
        prepare_refund(runtime, returned, 1, 1, "no-refund-liability-yet")
    assert retained_partial_state(runtime) == before


def test_preparer_cannot_review_or_post_own_partial_source(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice = create_partial_runtime(receipt_database)
    prepared = prepare_return(runtime, source_id, 4)
    before = retained_partial_state(runtime)
    with pytest.raises(FinancePostingError):
        phase(runtime, prepared, "review", "maker")
    assert retained_partial_state(runtime) == before
    reviewed = phase(runtime, prepared, "review", "checker")
    for who in ("maker", "checker"):
        with pytest.raises(FinancePostingError):
            phase(runtime, reviewed, "post", who)


def test_fractional_original_and_partial_return_preserve_scale_and_refuse_nonintegral_minor_cost(receipt_database: tuple[str, str]) -> None:
    # A non-integral requested money portion must refuse; no quantity or cost
    # value is rounded to fit a financial posting contract.
    runtime, source_id, _invoice = create_fractional_partial_runtime(receipt_database)
    before = retained_partial_state(runtime)
    with pytest.raises(FinancePostingError, match="integral"):
        prepare_return(runtime, source_id, 2, 0, "unrepresentable-original-cost")
    assert retained_partial_state(runtime) == before
    args = request(source_id, 1250)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant)
        with pytest.raises(FinancePostingError):
            owner.prepare(replace(args, quantity_scaled=True), command_id="boolean-quantity", actor=actor)
    result = posted(runtime, prepare_return(runtime, source_id, 1250, 0, "fractional-source-return"))
    assert (result["quantity_precision"], result["quantity_scaled"], result["credit_minor"], result["cogs_restored_minor"]) == (3, 1250, 5625, 1500)
    state = balance(runtime, source_id)
    assert state["quantity_precision"] == 3 and state["remaining_quantity_scaled"] == 1250 and state["outstanding_minor"] == 5625


def test_existing_rounded_fractional_original_posts_exact_half_of_retained_revenue_and_cost(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, invoice_id = create_fractional_partial_runtime(receipt_database, unit_price_minor=951)
    with runtime.actor("maker") as (connection, _, _actor):
        original = connection.execute("SELECT total_minor FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s",
                                      (runtime.tenant, invoice_id)).fetchone()
        assert original["total_minor"] == 2378
    before = retained_partial_state(runtime)
    with pytest.raises(FinancePostingError, match="integral"):
        prepare_return(runtime, source_id, 1, 0, "refuse-unrepresentable-rounded-portion")
    assert retained_partial_state(runtime) == before
    returned = posted(runtime, prepare_return(runtime, source_id, 1250, 0, "rounded-original-half-return"))
    assert (returned["quantity_precision"], returned["credit_minor"], returned["cogs_restored_minor"],
            returned["receivable_released_minor"], returned["refund_entitlement_delta_minor"]) == (3, 1189, 1500, 1189, 0)
    state = balance(runtime, source_id)
    assert (state["gross_minor"], state["remaining_quantity_scaled"], state["outstanding_minor"]) == (2378, 1250, 1189)
    values = balances(runtime)
    assert (values["INVENTORY"], values["CLEARING"], values["COGS"], values["AR"], values["REVENUE"]) == (10500, -12000, 1500, 1189, -1189)


def test_existing_consumable_stock_source_posts_partial_credit_and_original_fifo_restoration(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = create_fractional_partial_runtime(receipt_database, item_type="Consumable", quantity="2")
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT item_type FROM reconforge.inventory_items WHERE tenant_id=%s AND item_code='ITEM'",
                                  (runtime.tenant,)).fetchone()["item_type"] == "Consumable"
    returned = posted(runtime, prepare_return(runtime, source_id, 1000, 0, "consumable-original-half-return"))
    assert (returned["quantity_precision"], returned["quantity_scaled"], returned["credit_minor"],
            returned["cogs_restored_minor"], returned["receivable_released_minor"]) == (3, 1000, 4500, 1200, 4500)
    state = balance(runtime, source_id)
    assert (state["gross_minor"], state["remaining_quantity_scaled"], state["outstanding_minor"]) == (9000, 1000, 4500)
    values = balances(runtime)
    assert (values["INVENTORY"], values["CLEARING"], values["COGS"], values["AR"], values["REVENUE"]) == (10800, -12000, 1200, 4500, -4500)


def settlement_private_directory() -> Path | None:
    private_output = os.environ.get("RECONFORGE_PARTIAL_CYCLE_PRIVATE_OUTPUT")
    if private_output is None:
        return None
    destination = Path(private_output)
    if not destination.is_absolute() or ".." in destination.parts:
        raise AssertionError("Native originals require an explicit owned private directory.")
    for ancestor in (destination, *destination.parents):
        attributes = getattr(ancestor.lstat(), "st_file_attributes", 0)
        if ancestor.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise AssertionError("Native originals cannot follow linked private directories.")
    if not destination.is_dir():
        raise AssertionError("Native originals require an existing private directory.")
    return destination.resolve(strict=True)


def settlement_originals(runtime: ReceiptRuntime, checkpoint: str) -> dict[str, tuple[str, ...]]:
    """Keep exact SQL row text; the optional destination is explicitly private."""
    from psycopg import sql

    state = {}
    with runtime.actor("maker") as (connection, _, _actor):
        tables = connection.execute("""SELECT table_name FROM information_schema.tables
            WHERE table_schema='reconforge' AND table_type='BASE TABLE'
            AND table_name ~ '^(customer_return_|customer_partial_return_|commercial_collection_|stock_|finance_|ar_|inventory_|operational_finance_|domain_audit_|outbox_)'
            ORDER BY table_name""").fetchall()
        assert len(SETTLEMENT_TABLES) == len(set(SETTLEMENT_TABLES)) == 79
        if tuple(row["table_name"] for row in tables) != SETTLEMENT_TABLES:
            raise AssertionError("Native settlement originals require the exact 79-table family.")
        for row in tables:
            state[row["table_name"]] = tuple(value["original"] for value in connection.execute(sql.SQL(
                "SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text"
            ).format(sql.Identifier(row["table_name"])), (runtime.tenant,)).fetchall())
    destination = settlement_private_directory()
    if destination is not None:
        assert checkpoint in {"split-before-credit", "split-after-credit", "split-after-2000", "split-after-refusal",
                              "split-after-1500", "race-before-credit", "race-after-refusal"}
        with (destination / ("native-partial-settlement-" + checkpoint + "-original-v2.json")).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump({"schema_version": "native-partial-settlement-row-text-v2", "checkpoint": checkpoint,
                       "tenant_id": runtime.tenant, "tables": state}, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
    return state


def settlement_totals(runtime: ReceiptRuntime, expected_effects: int, expected_lines: int, expected_turnover: int) -> None:
    with runtime.actor("maker") as (connection, _, _actor):
        row = connection.execute("""SELECT count(DISTINCT f.id) effects,count(*) lines,
            sum(l.debit_minor)::text debit,sum(l.credit_minor)::text credit
            FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entry_lines l
            ON(l.tenant_id,l.entry_id)=(f.tenant_id,f.entry_id) WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert (row["effects"], row["lines"], Fraction(row["debit"]), Fraction(row["credit"])) == (
            expected_effects, expected_lines, expected_turnover, expected_turnover)


def test_credit_adjusted_residual_accepts_two_genuine_cash_installments_and_rolls_back_overcap(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, invoice_id = create_two_layer_source(receipt_database)
    settlement_originals(runtime, "split-before-credit")
    posted(runtime, prepare_return(runtime, source_id, 12, 0, "split-credit-first"))
    settlement_originals(runtime, "split-after-credit")
    assert balance(runtime, source_id)["outstanding_minor"] == 3500
    complete(runtime, prepare(runtime, invoice_id, 2000, "SPLIT-2000"), "SPLIT-2000")
    before = settlement_originals(runtime, "split-after-2000")
    assert (balance(runtime, source_id)["outstanding_minor"], balance(runtime, source_id)["history_version"]) == (1500, 2)
    with pytest.raises(FinancePostingError) as refused:
        prepare(runtime, invoice_id, 2000, "SPLIT-OVERCAP")
    assert refused.value.code == "collection_amount_invalid"
    if settlement_originals(runtime, "split-after-refusal") != before:
        raise AssertionError("A refused overcap cash preparation changed native original rows.")
    complete(runtime, prepare(runtime, invoice_id, 1500, "SPLIT-1500"), "SPLIT-1500")
    settlement_originals(runtime, "split-after-1500")
    current = balance(runtime, source_id)
    assert (current["outstanding_minor"], current["collected_minor"], current["history_version"], current["refund_due_minor"]) == (0, 13500, 3, 0)
    values = balances(runtime)
    assert (values["INVENTORY"], values["CLEARING"], values["COGS"], values["AR"], values["CASH"], values["REVENUE"]) == (26000, -32000, 6000, 0, 13500, -13500)
    settlement_totals(runtime, 9, 18, 205000)
    with runtime.actor("maker") as (connection, _, _actor):
        events = connection.execute("""SELECT sequence,kind,amount_minor FROM reconforge.customer_partial_return_history
            WHERE tenant_id=%s ORDER BY sequence""", (runtime.tenant,)).fetchall()
        assert [(r["sequence"], r["kind"], r["amount_minor"]) for r in events] == [(1, "Return", 0), (2, "Collection", 2000), (3, "Collection", 1500)]


def test_credit_post_precedes_waiting_cash_prepare_and_rechecks_the_committed_residual(receipt_database: tuple[str, str]) -> None:
    import psycopg

    runtime, source_id, invoice_id = create_two_layer_source(receipt_database)
    posted(runtime, prepare_return(runtime, source_id, 12, 0, "race-first-credit"))
    reviewed = phase(runtime, prepare_return(runtime, source_id, 3, 1, "race-remaining-credit"), "review", "checker")
    settlement_originals(runtime, "race-before-credit")
    starting: Queue[tuple[str, int]] = Queue()
    edges = []

    def post_credit() -> dict[str, Any]:
        with runtime.actor("poster") as (connection, _, actor):
            starting.put(("credit", connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]))
            return PostgresCustomerPartialReturnsRepository(connection, runtime.tenant).post(reviewed["id"],
                expected_plan_digest=reviewed["plan_digest"], command_id="race-owned-credit-post",
                reason="Post the independently reviewed credit before waiting cash", actor=actor)

    def prepare_cash() -> str:
        with runtime.actor("maker") as (connection, _, actor):
            starting.put(("cash", connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]))
            args = CommercialCollectionPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY", source_id=invoice_id,
                journal_code="CASH", period_id="period", posting_date="2026-10-14", debit_account_code="CASH", credit_account_code="AR",
                reason="Recheck the original invoice after the actual customer wait", amount_minor=3500, receipt_number="RACE-CASH-3500")
            with pytest.raises(FinancePostingError) as refused:
                PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(args, command_id="race-cash-prepare", actor=actor)
            return refused.value.code

    def wait_edge(waiter: int, predecessor: int) -> None:
        with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
            deadline = time.monotonic() + 6
            while True:
                blockers = observer.execute("SELECT pg_blocking_pids(%s)", (waiter,)).fetchone()[0]
                if predecessor in blockers:
                    edges.append({"waiter_pid": waiter, "blocking_pids": sorted(blockers), "expected_predecessor_pid": predecessor})
                    return
                if time.monotonic() >= deadline:
                    raise AssertionError("The actual customer wait queue was not observed.")
                time.sleep(.02)

    with ThreadPoolExecutor(max_workers=2) as workers:
        with runtime.actor("maker") as (holder, _, _actor):
            customer_id = holder.execute("SELECT customer_id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s",
                                         (runtime.tenant, invoice_id)).fetchone()["customer_id"]
            holder.execute("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE", (runtime.tenant, customer_id))
            holder_pid = holder.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            credit = workers.submit(post_credit)
            name, credit_pid = starting.get(timeout=6)
            assert name == "credit"
            wait_edge(credit_pid, holder_pid)
            cash = workers.submit(prepare_cash)
            name, cash_pid = starting.get(timeout=6)
            assert name == "cash"
            wait_edge(cash_pid, credit_pid)
            assert not credit.done() and not cash.done()
        assert credit.result(timeout=60)["phase"] == 2
        assert cash.result(timeout=60) == "collection_source_changed"
    settlement_originals(runtime, "race-after-refusal")
    destination = settlement_private_directory()
    if destination is not None:
        with (destination / "native-partial-settlement-race-lock-graph-original-v1.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump({"schema_version": "native-partial-settlement-wait-graph-v1", "edges": edges}, stream, sort_keys=True)
            stream.write("\n")
    current = balance(runtime, source_id)
    assert (current["outstanding_minor"], current["collected_minor"], current["history_version"], current["refund_due_minor"]) == (0, 10000, 2, 10000)
    values = balances(runtime)
    assert (values["INVENTORY"], values["CLEARING"], values["COGS"], values["AR"], values["CASH"], values["REVENUE"], values["REFUND"]) == (32000, -32000, 0, 0, 10000, 0, -10000)
    # The last revenue credit has three real lines: DR revenue, CR remaining
    # AR 3500, CR refund liability 10000. No synthetic two-line assumption.
    settlement_totals(runtime, 9, 19, 221000)
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
