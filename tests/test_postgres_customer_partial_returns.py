"""Actual governed partial credit/refund operations on ordinary PostgreSQL.

The independent posted-cycle oracle is owned separately. These cases exercise
the real command owner and retained native effects, not synthetic SQL postings.
"""

from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.customer_partial_return_commands import (
    CustomerPartialRefundPreparation,
    CustomerPartialReturnPreparation,
    CustomerPartialReversePreparation,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from tests.test_postgres_commercial_collections import complete, prepare
from tests.test_postgres_customer_partial_return_source import two_layer_source
from tests.test_postgres_customer_returns import balances, configure_runtime, create_runtime, retained_state
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database
from tests.test_postgres_stock_sales import create_reserved_order, create_stock_runtime, execute

_ = receipt_database, two_layer_source
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}


def create_partial_runtime(database: tuple[str, str], paid: int = 10000, *, quantity: str | None = None) -> tuple[ReceiptRuntime, str, str]:
    return create_runtime(database, paid=paid, quantity=quantity)


def retained_partial_state(runtime: ReceiptRuntime) -> dict[str, Any]:
    from psycopg import sql
    state = retained_state(runtime)
    with runtime.actor("maker") as (connection, _, _actor):
        names = connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='reconforge' AND table_name LIKE 'customer_partial_return_%' ORDER BY table_name").fetchall()
        for row in names:
            state[row["table_name"]] = tuple(item["original"] for item in connection.execute(
                sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text").format(sql.Identifier(row["table_name"])),
                (runtime.tenant,)).fetchall())
    return state


def create_fractional_partial_runtime(database: tuple[str, str]) -> tuple[ReceiptRuntime, str, str]:
    base = create_receipt_runtime(database)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        PostgresInventoryCoreRepository(connection, base.tenant).upsert_uom(uom_code="EA", name="Each", decimal_places=3, workspace="work")
    runtime = create_stock_runtime(database, base_runtime=base)
    configure_runtime(runtime)
    sale = create_reserved_order(runtime, "FRACTIONAL-ORIGINAL", "2.5")
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
