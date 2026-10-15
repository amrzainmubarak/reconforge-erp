"""Genuine147-compatible originals with governed148 remaining-value returns."""

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.customer_partial_return_commands import CustomerPartialReversePreparation
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from tests.test_postgres_customer_partial_returns import SCOPE, request, retained_partial_state
from tests.test_postgres_customer_returns import balances, configure_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database
from tests.test_postgres_inventory_receipt_posting import request as receipt_request
from tests.test_postgres_stock_sales import create_stock_runtime, execute
from tests.test_postgres_stock_sales import repository as stock_repository

_ = receipt_database


def test_native_v2_fifo_uses_exact_division_at_large_half_and_integer_boundaries(receipt_database: tuple[str,str]) -> None:
    runtime=create_receipt_runtime(receipt_database)
    with runtime.actor("maker") as (connection,_,_actor):
        for selected,expected in ((4499999999999499999,4499999999999),(8999999999999999999,9000000000000)):
            row=connection.execute("SELECT reconforge.customer_partial_return_v2_fifo(%s,%s,%s) value",
                                   (9000000000000,9000000000000000000,selected)).fetchone()
            assert row["value"]==expected


def create_remainder_runtime(database: tuple[str, str], *, zero: bool = False) -> tuple[ReceiptRuntime, str]:
    """Use only supported native receipt/sale owners; no forged source rows."""
    base = create_receipt_runtime(database)
    if zero:
        with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
            inventory = PostgresInventoryCoreRepository(connection, base.tenant)
            inventory.upsert_uom(uom_code="TENTH", name="Exact original tenths", decimal_places=1, workspace="work")
            inventory.upsert_item(item_code="ITEM", name="Original fractional item", organization_code="ORG", uom_code="TENTH",
                                  inventory_account_code="INVENTORY", workspace="work")
    runtime = create_stock_runtime(database, base_runtime=base, seed_stock=False)
    configure_runtime(runtime)
    quantity, cost, unit = ("0.3", 1, 3) if zero else ("3", 1001, 1000)
    receipt = replace(receipt_request("REMAINDER-RAW"), quantity=quantity, total_value_minor=cost)
    with runtime.actor("maker") as (_, owner, actor):
        plan = owner.prepare_receipt(receipt, command_id="remainder-receipt-prepare", actor=actor)
    with runtime.actor("checker") as (_, owner, actor):
        review = owner.review(plan["plan_id"], command_id="remainder-receipt-review", expected_plan_digest=plan["plan_digest"],
                             reason="Exact original quantity and minor units", actor=actor)
    with runtime.actor("poster") as (_, owner, actor):
        owner.commit(plan["plan_id"], command_id="remainder-receipt-post", expected_review_digest=review["review_digest"],
                     reason="Publish original cost through the existing owner", actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        sale = stock_repository(connection, runtime).create(StockOrder("REMAINDER-ORIGINAL", "CUSTOMER", "CUSTOMER-PO-1", "ITEM",
            "MAIN", "STOCK", quantity, unit, "USD", "2026-10-09", "Existing valid original merchandise"),
            command_id="remainder-original-create", actor=actor)
    for operation, who in (("submit", "maker"), ("approve", "checker"), ("reserve", "maker")):
        sale = execute(runtime, sale, operation, who)
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    sale = execute(runtime, sale, "review-issue", "checker")
    sale = execute(runtime, sale, "deliver", "poster")
    invoice = SalesInvoicePreparation("REMAINDER-INVOICE", "2026-10-09", "2026-10-31", "SALES", "period", "AR", "REVENUE",
                                      "Native original rounded merchandise").payload()
    invoice.pop("reason")
    sale = execute(runtime, sale, "prepare-invoice", "maker", invoice)
    sale = execute(runtime, sale, "review-invoice", "checker")
    sale = execute(runtime, sale, "invoice", "poster")
    return runtime, sale["id"]


def prepare_v2(runtime: ReceiptRuntime, source: str, quantity: int, version: int, command: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
        args = request(source, quantity, version)
        result = owner.prepare(args, command_id=command, actor=actor)
        assert owner.prepare(args, command_id=command, actor=actor) == result
        return result


def phase_v2(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, who: str) -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": plan["id"] + ":" + operation,
                "reason": "Actual remaining-value " + operation, "actor": actor}
        result = getattr(owner, operation)(plan["id"], **args)
        assert getattr(owner, operation)(plan["id"], **args) == result
        return result


def post_v2(runtime: ReceiptRuntime, plan: dict[str, Any]) -> dict[str, Any]:
    return phase_v2(runtime, phase_v2(runtime, plan, "review", "checker"), "post", "poster")


def reverse_v2(runtime: ReceiptRuntime, plan: dict[str, Any], version: int) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
        inverse = owner.prepare_reversal(CustomerPartialReversePreparation(plan["id"], "period", "2026-10-14",
            "Reverse the exact owned remaining-value effect", version), command_id=plan["id"] + ":inverse", actor=actor)
    return post_v2(runtime, inverse)


def current_v2(runtime: ReceiptRuntime, source: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2).balance(source, SCOPE, actor=actor)


def test_actual_remaining_cost_1001_over_three_units_is_conserved_with_cancel_and_exact_inverse(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database)
    first = post_v2(runtime, prepare_v2(runtime, source, 1, 0, "remaining-first"))
    assert (first["credit_minor"], first["cogs_restored_minor"], first["allocation_policy"]) == (1000, 334, "remaining-original-v1")
    inverse = reverse_v2(runtime, first, 1)
    assert inverse["operation"] == "ReverseReturn" and inverse["cogs_restored_minor"] == 334
    pending = prepare_v2(runtime, source, 2, 2, "remaining-cancel")
    phase_v2(runtime, pending, "cancel", "checker")
    assert current_v2(runtime, source)["history_version"] == 2
    costs = []
    for index, version in enumerate((2, 3, 4)):
        plan = post_v2(runtime, prepare_v2(runtime, source, 1, version, "remaining-cut-" + str(index)))
        costs.append(plan["cogs_restored_minor"])
    assert costs == [334, 334, 333]
    state = current_v2(runtime, source)
    assert state["history_version"] == 5 and state["outstanding_minor"] == state["remaining_quantity_scaled"] == 0
    values = balances(runtime)
    assert (values["INVENTORY"], values["CLEARING"], values["COGS"], values["AR"], values["REVENUE"]) == (1001, -1001, 0, 0, 0)


def test_actual_zero_financial_legs_keep_physical_history_three_humans_and_purpose_owned_inverse(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    first = prepare_v2(runtime, source, 1, 0, "zero-first")
    assert first["amount_minor"] == first["credit_minor"] == first["cogs_restored_minor"] == 0 and first["entries"] == []
    first = post_v2(runtime, first)
    assert first["phase"] == 2 and current_v2(runtime, source)["history_version"] == 1
    inverse = reverse_v2(runtime, first, 1)
    assert inverse["entries"] == [] and inverse["phase"] == 2
    zero_again = post_v2(runtime, prepare_v2(runtime, source, 1, 2, "zero-again"))
    assert zero_again["entries"] == []
    revenue_only = post_v2(runtime, prepare_v2(runtime, source, 1, 3, "revenue-only"))
    assert [part["purpose"] for part in revenue_only["entries"]] == ["RevenueCredit"]
    cost_only = post_v2(runtime, prepare_v2(runtime, source, 1, 4, "cost-only"))
    assert [part["purpose"] for part in cost_only["entries"]] == ["CostRestoration"]
    inverse_cost = reverse_v2(runtime, cost_only, 5)
    assert [part["purpose"] for part in inverse_cost["entries"]] == ["ReverseCostRestoration"]
    with runtime.actor("maker") as (connection, _, _actor):
        entry = connection.execute("SELECT entry_number FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s",
                                   (runtime.tenant, inverse_cost["entries"][0]["entry_id"])).fetchone()
        assert entry["entry_number"] == inverse_cost["id"].upper() + "-C"
        assert not connection.execute("SELECT 1 FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND debit_minor=0 AND credit_minor=0",
                                      (runtime.tenant,)).fetchone()
    state = current_v2(runtime, source)
    assert (state["history_version"], state["remaining_quantity_scaled"], state["credited_minor"]) == (6, 1, 1)


def test_protocol_one_cannot_list_read_mutate_or_replay_a_version_two_owner(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database)
    plan = prepare_v2(runtime, source, 1, 0, "protocol-command")
    before = retained_partial_state(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        legacy = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant)
        assert legacy.list_plans(SCOPE, actor=actor) == {"plans": []}
        for operation in (lambda: legacy.get(plan["id"], actor=actor), lambda: legacy.balance(source, SCOPE, actor=actor),
                          lambda: legacy.prepare(request(source, 1), command_id="protocol-command", actor=actor)):
            with pytest.raises(FinancePostingError) as denied:
                operation()
            assert denied.value.code in {"customer_partial_return_protocol_conflict", "customer_partial_return_command_conflict"}
    assert retained_partial_state(runtime) == before


@pytest.mark.parametrize("change", ["quantity", "cost", "domain-witness"])
def test_native_reverse_plan_cannot_change_original_magnitudes_or_allocation_witness(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    import psycopg

    runtime, source = create_remainder_runtime(receipt_database)
    parent = post_v2(runtime, prepare_v2(runtime, source, 1, 0, "reverse-pin-original"))
    before = retained_partial_state(runtime)
    original_save = PostgresCustomerPartialReturnsRepository._save

    def forged_save(owner: Any, supplied: dict[str, Any], actor: Any) -> None:
        payload = deepcopy(supplied)
        if payload["operation"] == "ReverseReturn":
            if change == "quantity":
                payload["quantity_scaled"] += 1
            elif change == "cost":
                payload["cogs_restored_minor"] += 1
                payload["amount_minor"] += 1
            else:
                payload["domain_plan"]["portions"][0]["before_value_minor"] += 1
        original_save(owner, payload, actor)

    monkeypatch.setattr(PostgresCustomerPartialReturnsRepository, "_save", forged_save)
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        with runtime.actor("maker") as (connection, _, actor):
            owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
            owner.prepare_reversal(CustomerPartialReversePreparation(parent["id"], "period", "2026-10-14",
                "Attempt to alter an original inverse magnitude", 1), command_id="forged-reverse-pin", actor=actor)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert refused.value.diag.constraint_name == "customer_partial_return_owner"
    assert retained_partial_state(runtime) == before
