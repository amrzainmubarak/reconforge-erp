"""Real authoritative multi-line commercial orders and partial stock-to-cash."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.stock_commerce import CommercialLine, CommercialOrder
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_stock_commerce import PostgresStockCommerceRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database, request
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database


def repository(connection: Any, runtime: ReceiptRuntime) -> PostgresStockCommerceRepository:
    return PostgresStockCommerceRepository(connection, runtime.tenant, workspace_id="work", organization_id="org",
        legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY")


def commercial_order(runtime: ReceiptRuntime, number: str = "DISTRIBUTOR") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        result = owner.create(CommercialOrder(number, "CUSTOMER", "PO-DISTRIBUTOR", "USD", "2026-10-09",
            (CommercialLine("ITEM", "MAIN", "STOCK", "10", 5000, "Physical product", 1000),)), command_id=number + ":create", actor=actor)
        result = owner.act(result["id"], "submit", expected_version=result["row_version"], command_id=number + ":submit",
            reason="Commercial terms agreed", parameters={}, actor=actor)
    return act(runtime, result, "approve", "checker")


def act(runtime: ReceiptRuntime, result: dict[str, Any], operation: str, who: str,
        parameters: dict[str, Any] | None = None, command_id: str | None = None) -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        owner = repository(connection, runtime)
        acknowledgement = owner.act(result["id"], operation, expected_version=result["row_version"],
            command_id=command_id or f"{result['number']}:{result['row_version']}:{operation}", reason="Actual " + operation,
            parameters=parameters or {}, actor=actor)
        view = owner.get(result["id"], actor=actor)
        assert view["row_version"] >= acknowledgement["row_version"]
        return view


def complete_tranche(runtime: ReceiptRuntime, result: dict[str, Any], quantity: str, suffix: str, line_number: int = 1) -> dict[str, Any]:
    result = act(runtime, result, "open-tranche", "maker", {"line_number": line_number, "quantity": quantity})
    tranche = result["lines"][line_number - 1]["tranches"][-1]["id"]
    def proceed(operation: str, who: str, values: dict[str, Any] | None = None) -> None:
        nonlocal result
        result = act(runtime, result, operation, who, {"tranche_id": tranche, **(values or {})})
    proceed("approve-tranche", "checker")
    proceed("prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    proceed("review-issue", "checker")
    proceed("deliver", "poster")
    proceed("prepare-invoice", "maker", {"invoice_number": "DISTRIBUTOR-INV-" + suffix, "invoice_date": "2026-10-09",
        "due_date": "2026-10-31", "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"})
    proceed("review-invoice", "checker")
    proceed("invoice", "poster")
    proceed("prepare-collection", "maker", {"receipt_number": "DISTRIBUTOR-CASH-" + suffix, "receipt_date": "2026-10-10",
        "journal_code": "CASH", "period_id": "period", "cash_account_code": "CASH"})
    proceed("review-collection", "checker")
    proceed("collect", "poster")
    return result


def test_actual_two_partial_shipments_invoices_and_collections_conserve_parent(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    result = commercial_order(runtime)
    result = complete_tranche(runtime, result, "3", "FIRST")
    line = result["lines"][0]
    assert (line["committed_quantity_scaled"], line["delivered_quantity_scaled"], line["invoiced_minor"], line["collected_minor"]) == ("3", "3", "13500", "13500")
    result = complete_tranche(runtime, result, "7", "SECOND")
    line = result["lines"][0]
    assert (line["committed_quantity_scaled"], line["delivered_quantity_scaled"], line["invoiced_minor"], line["collected_minor"]) == ("10", "10", "45000", "45000")
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor) == result
        assert dict(connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == {"q": 0, "v": 0}
        totals = connection.execute("""SELECT sum(e.total_debit_minor) d,sum(e.total_credit_minor) c FROM reconforge.finance_posting_effects f
            JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert totals["d"] == totals["c"] == 114000
    with pytest.raises(FinancePostingError, match="remainder"):
        act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "1"})


def test_current_commercial_version_serializes_concurrent_partial_claims_and_exact_replay(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    result = commercial_order(runtime)
    def attempt(index: int) -> dict[str, Any] | str:
        try:
            return act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "6"}, command_id=f"concurrent-{index}")
        except FinancePostingError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=4) as executor:
        answers = list(executor.map(attempt, range(4)))
    accepted = [(index, value) for index, value in enumerate(answers) if isinstance(value, dict)]
    assert len(accepted) == 1
    assert [value for value in answers if isinstance(value, str)] == ["commerce_version_conflict"] * 3
    index, response = accepted[0]
    assert act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "6"}, command_id=f"concurrent-{index}") == response
    with pytest.raises(FinancePostingError, match="different"):
        act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "5"}, command_id=f"concurrent-{index}")


def test_direct_child_transition_and_line_tamper_roll_back_at_sql_boundary(receipt_database: tuple[str, str]) -> None:
    import psycopg
    runtime = create_stock_runtime(receipt_database)
    result = commercial_order(runtime)
    result = act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "4"})
    child_id = result["lines"][0]["tranches"][0]["stock_order_id"]
    with pytest.raises(psycopg.errors.CheckViolation, match="outside its atomic commercial"), runtime.actor("checker") as (connection, _, actor):
        native = repository(connection, runtime).native
        native.act(child_id, "approve", expected_version=2, command_id="unowned-child-transition", reason="Bypass parent", parameters={}, actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"), runtime.actor("maker") as (connection, _, actor):
        connection.execute("SELECT set_config('app.stock_commerce_actor_id',%s,true)", (actor.user_id,))
        connection.execute("UPDATE reconforge.stock_commerce_lines SET quantity_scaled=100 WHERE tenant_id=%s AND order_id=%s", (runtime.tenant, result["id"]))
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor) == result


def test_same_human_cannot_approve_commercial_terms(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    with runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        result = owner.create(CommercialOrder("SOD", "CUSTOMER", "PO", "USD", "2026-10-09",
            (CommercialLine("ITEM", "MAIN", "STOCK", "2", 5000, "Product"),)), command_id="sod-create", actor=actor)
        result = owner.act(result["id"], "submit", expected_version=1, command_id="sod-submit", reason="Submit", parameters={}, actor=actor)
    with pytest.raises(FinancePostingError, match="cannot approve"):
        act(runtime, result, "approve", "maker")


def test_multi_product_multi_warehouse_partial_commerce_and_catalog_keysets(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    with runtime.actor("maker") as (connection, _, _actor):
        inventory = PostgresInventoryCoreRepository(connection, runtime.tenant)
        inventory.upsert_item(item_code="ITEM-B", name="Product B", organization_code="ORG", uom_code="EA", inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_warehouse(warehouse_code="SOUTH", name="South distribution", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="SOUTH", location_code="STOCK", name="South stock", organization_code="ORG", workspace="work")
    with runtime.actor("maker") as (_, participant, actor):
        receipt = participant.prepare_receipt(replace(request("INBOUND-B"), item_code="ITEM-B", location_code="SOUTH/STOCK",
            posting_date="2026-10-04", quantity="8", total_value_minor=16000), command_id="south-inbound-prepare", actor=actor)
    with runtime.actor("checker") as (_, participant, actor):
        review = participant.review(receipt["plan_id"], command_id="south-inbound-review", expected_plan_digest=receipt["plan_digest"], reason="Independent South receipt", actor=actor)
    with runtime.actor("poster") as (_, participant, actor):
        participant.commit(receipt["plan_id"], command_id="south-inbound-post", expected_review_digest=review["review_digest"], reason="Publish South inventory", actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        ack = owner.create(CommercialOrder("MULTI", "CUSTOMER", "MULTI-PO", "USD", "2026-10-09", (
            CommercialLine("ITEM", "MAIN", "STOCK", "10", 5000, "North product", 1000),
            CommercialLine("ITEM-B", "SOUTH", "STOCK", "8", 3000, "South product", 0))), command_id="multi-create", actor=actor)
        result = owner.get(ack["id"], actor=actor)
        first = owner.catalog(prefix="ITEM", after="", limit=1, actor=actor)
        assert first["items"][0]["item_code"] == "ITEM"
        assert first["next_cursor"] == "ITEM"
        second = owner.catalog(prefix="ITEM", after=first["next_cursor"], limit=1, actor=actor)
        assert second["items"][0]["item_code"] == "ITEM-B"
        assert second["next_cursor"] is None
    result = act(runtime, result, "submit", "maker")
    result = act(runtime, result, "approve", "checker")
    result = complete_tranche(runtime, result, "3", "MULTI-NORTH-FIRST", 1)
    result = complete_tranche(runtime, result, "5", "MULTI-SOUTH-FIRST", 2)
    assert result["total_minor"] == "69000"
    assert [line["collected_minor"] for line in result["lines"]] == ["13500", "15000"]
    result = complete_tranche(runtime, result, "7", "MULTI-NORTH-FINAL", 1)
    result = complete_tranche(runtime, result, "3", "MULTI-SOUTH-FINAL", 2)
    assert [line["delivered_quantity_scaled"] for line in result["lines"]] == ["10", "8"]
    assert [line["invoiced_minor"] for line in result["lines"]] == ["45000", "24000"]
    assert [line["collected_minor"] for line in result["lines"]] == ["45000", "24000"]
