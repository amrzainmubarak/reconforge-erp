"""Actual nonowner PostgreSQL stock-to-cash and reservation ownership."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_stock_sales import OPERATION_PERMISSIONS, PostgresStockSalesRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database, request
from tests.test_postgres_sales_revenue import create_sales_runtime

_ = receipt_database


def repository(connection: Any, runtime: ReceiptRuntime) -> PostgresStockSalesRepository:
    return PostgresStockSalesRepository(connection, runtime.tenant, workspace_id="work", organization_id="org",
                                       legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY")


def create_stock_runtime(database: tuple[str, str]) -> ReceiptRuntime:
    runtime = create_sales_runtime(database)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*OPERATION_PERMISSIONS.values())):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    with runtime.actor("maker") as (_, participant, actor):
        plan = participant.prepare_receipt(request(), command_id="inbound-prepare", actor=actor)
    with runtime.actor("checker") as (_, participant, actor):
        review = participant.review(plan["plan_id"], command_id="inbound-review", expected_plan_digest=plan["plan_digest"],
                                   reason="Independent inventory receipt", actor=actor)
    with runtime.actor("poster") as (_, participant, actor):
        participant.commit(plan["plan_id"], command_id="inbound-commit", expected_review_digest=review["review_digest"],
                           reason="Publish actual FIFO stock", actor=actor)
    return runtime


@pytest.fixture
def stock_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_stock_runtime(receipt_database)


def create_reserved_order(runtime: ReceiptRuntime, number: str = "PRODUCT-1", quantity: str = "5") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        result = owner.create(StockOrder(number, "CUSTOMER", "CUSTOMER-PO-1", "ITEM", "MAIN", "STOCK", quantity,
                                        5000, "USD", "2026-10-09", "Five physical products", 1000),
                              command_id=number + ":create", actor=actor)
        result = owner.act(result["id"], "submit", expected_version=1, command_id=number + ":submit",
                           reason="Customer terms agreed", parameters={}, actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        result = repository(connection, runtime).act(result["id"], "approve", expected_version=2,
            command_id=number + ":approve", reason="Approved exact discount and terms", parameters={}, actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        return repository(connection, runtime).act(result["id"], "reserve", expected_version=3,
            command_id=number + ":reserve", reason="Reserve customer quantity", parameters={}, actor=actor)


def execute(runtime: ReceiptRuntime, result: dict[str, Any], operation: str, actor_name: str,
            parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    with runtime.actor(actor_name) as (connection, _, actor):
        return repository(connection, runtime).act(result["id"], operation, expected_version=result["row_version"],
            command_id=result["number"] + ":" + operation, reason="Actual " + operation, parameters=parameters or {}, actor=actor)


def complete_stock_sale(runtime: ReceiptRuntime) -> dict[str, Any]:
    result = create_reserved_order(runtime)
    result = execute(runtime, result, "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    result = execute(runtime, result, "review-issue", "checker")
    result = execute(runtime, result, "deliver", "poster")
    invoice = SalesInvoicePreparation("PRODUCT-INVOICE-1", "2026-10-09", "2026-10-31", "SALES", "period",
                                      "AR", "REVENUE", "Actual product sale").payload()
    invoice.pop("reason")
    result = execute(runtime, result, "prepare-invoice", "maker", invoice)
    result = execute(runtime, result, "review-invoice", "checker")
    result = execute(runtime, result, "invoice", "poster")
    result = execute(runtime, result, "prepare-collection", "maker", {
        "receipt_number": "PRODUCT-CASH-1", "receipt_date": "2026-10-10", "journal_code": "CASH",
        "period_id": "period", "cash_account_code": "CASH"})
    result = execute(runtime, result, "review-collection", "checker")
    return execute(runtime, result, "collect", "poster")


def test_actual_stock_to_cash_has_exact_fifo_cogs_revenue_cash_and_lost_ack(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    result = complete_stock_sale(runtime)
    assert (result["status"], result["row_version"], result["total_minor"], result["cogs_minor"]) == ("Paid", 13, "22500", "6000")
    with runtime.actor("poster") as (connection, _, actor):
        assert repository(connection, runtime).act(result["id"], "collect", expected_version=12,
            command_id="PRODUCT-1:collect", reason="Actual collect", parameters={}, actor=actor) == result
        assert dict(connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s",
                                       (runtime.tenant,)).fetchone()) == {"remaining_quantity_scaled": 5, "remaining_value_minor": 6000}
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 4
        assert connection.execute("SELECT status FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s",
                                  (runtime.tenant, result["invoice_id"])).fetchone()["status"] == "Paid"
        assert connection.execute("SELECT state FROM reconforge.stock_sales_reservations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["state"] == "Consumed"


def test_independent_review_and_native_detached_cogs_rollback(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    with pytest.raises(FinancePostingError):
        execute(runtime, result, "review-issue", "maker")
    result = execute(runtime, result, "review-issue", "checker")
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, actor):
        owner = repository(connection, runtime)
        entry = owner.finance.get_entry(result["cogs_entry_id"])
        owner.postings.post(entry["id"], command_id="detached-stock-gl", expected_validation_digest=entry["validation_digest"],
                            reason="Uncoordinated native posting", actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor)["status"] == "IssueReviewed"
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
    assert execute(runtime, result, "deliver", "poster")["status"] == "Delivered"


def test_six_concurrent_reservations_cannot_overcommit_ten_units(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    def reserve(index: int) -> bool:
        try:
            create_reserved_order(runtime, "RACE-" + str(index), "3")
            return True
        except Exception as exc:
            import psycopg
            assert isinstance(exc, psycopg.errors.CheckViolation)
            assert exc.diag.constraint_name == "stock_sales_owner_phase"
            return False
    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(reserve, range(6))) == 3
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT sum(quantity_scaled) n FROM reconforge.stock_sales_reservations WHERE tenant_id=%s AND state='Active'",
                                  (runtime.tenant,)).fetchone()["n"] == 9
