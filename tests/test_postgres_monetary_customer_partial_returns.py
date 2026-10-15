"""Actual149 commands; no synthetic journal insertion or mocked source owner.

The dedicated PostgreSQL gate supplies the owned ordinary-role fixture. Missing
native configuration fails that gate; this module adds no skip/xfail path.
Independent raw91 qualification is separate from these business regressions.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.monetary_customer_partial_return_commands import (
    MonetaryPartialRefundPreparation,
    MonetaryPartialReturnPreparation,
    MonetaryPartialReversePreparation,
)
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)
from reconforge.infrastructure.postgres_monetary_stock_sales import PostgresMonetaryStockSalesRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.test_postgres_customer_returns import configure_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_operational_fx_tax import native_balances, seed_fx_masters
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
DAY = "2026-10-16"


def _rate(value: str | None) -> dict[str, str] | None:
    return None if value is None else HistoricalRate(value, "Synthetic witnessed native spot", DAY + "T12:00:00Z").payload(DAY)


def _stock(connection: Any, runtime: ReceiptRuntime) -> PostgresMonetaryStockSalesRepository:
    return PostgresMonetaryStockSalesRepository(connection, runtime.tenant, **SCOPE, organization_code="ORG", entity_code="ENTITY")


def _act(runtime: ReceiptRuntime, order: dict[str, Any], operation: str, human: str,
         parameters: dict[str, Any] | None = None, suffix: str = "") -> dict[str, Any]:
    with runtime.actor(human) as (connection, _, actor):
        result = _stock(connection, runtime).act(order["id"], operation, expected_version=order["row_version"],
            command_id=order["number"] + ":" + operation + suffix, reason="Actual native monetary " + operation,
            parameters=parameters or {}, actor=actor)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        return result


def _source(database: tuple[str, str], *, foreign: bool, unit_price: int = 1000,
            original_rate: str = "1.25") -> tuple[ReceiptRuntime, dict[str, Any]]:
    runtime = create_stock_runtime(database)
    configure_runtime(runtime)
    seed_fx_masters(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        order = _stock(connection, runtime).create(StockOrder("ACTUAL-MONETARY", "FOREIGN" if foreign else "CUSTOMER",
            "SOURCE-PO", "ITEM", "MAIN", "STOCK", "10", unit_price, "EUR" if foreign else "USD", DAY,
            "Synthetic actual Stock and monetary original"), command_id="monetary:create", actor=actor)
    for operation, human, parameters in (
        ("submit", "maker", {}), ("approve", "checker", {}), ("reserve", "maker", {}),
        ("prepare-issue", "maker", {"posting_date": DAY, "period_id": "period", "policy_code": "FIFO"}),
        ("review-issue", "checker", {}), ("deliver", "poster", {}),
        ("prepare-invoice", "maker", {"invoice_number": "MONETARY-INVOICE", "invoice_date": DAY, "due_date": "2026-10-31",
            "journal_code": "STOCK", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE",
            "cash_account_code": "CASH", "refund_liability_account_code": "REFUND", "gain_account_code": "GAIN", "loss_account_code": "LOSS",
            "country_code": "EG", "transaction_class": "synthetic-stock", "original_rate": _rate(original_rate) if foreign else None,
            "taxes": [{"policy_id": "SYNTHETIC-VAT", "country_code": "EG", "transaction_class": "synthetic-stock",
                "effective_from": "2026-01-01", "effective_to": "2026-12-31", "rate": "0.14", "account_code": "TAX",
                "source": "Synthetic reviewed fraction", "version": "2026-v1"}]}),
        ("review-invoice", "checker", {}), ("invoice", "poster", {}),
    ):
        order = _act(runtime, order, operation, human, parameters)
    assert order["status"] == "Invoiced" and order["schema_version"] == "stock-sales-monetary-v2"
    return runtime, order


def _read(runtime: ReceiptRuntime, order: dict[str, Any]) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return _stock(connection, runtime).get(order["id"], actor=actor)


def _collect(runtime: ReceiptRuntime, order: dict[str, Any], amount: int, *, rate: str | None, number: str) -> dict[str, Any]:
    order = _act(runtime, _read(runtime, order), "prepare-collection", "maker", {
        "receipt_number": number, "receipt_date": DAY, "journal_code": "STOCK", "period_id": "period",
        "cash_account_code": "CASH", "amount_minor": amount, "settlement_rate": _rate(rate)}, suffix=number)
    order = _act(runtime, order, "review-collection", "checker", suffix=number)
    return _act(runtime, order, "collect", "poster", suffix=number)


def _return(runtime: ReceiptRuntime, order: dict[str, Any], quantity: int, version: int) -> dict[str, Any]:
    request = MonetaryPartialReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY",
        source_order_id=order["id"], quantity_scaled=quantity, period_id="period", posting_date=DAY,
        reason="Actual source-owned partial merchandise credit", expected_history_version=version)
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).prepare(request,
            command_id=f"return:{version}", actor=actor)


def _phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, human: str) -> dict[str, Any]:
    with runtime.actor(human) as (connection, _, actor):
        owner = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant)
        arguments = {"command_id": plan["id"] + ":" + operation, "expected_plan_digest": plan["plan_digest"],
                     "reason": "Actual independently governed " + operation, "actor": actor}
        result = getattr(owner, operation)(plan["id"], **arguments)
        assert getattr(owner, operation)(plan["id"], **arguments) == result
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        return result


def _posted(runtime: ReceiptRuntime, plan: dict[str, Any]) -> dict[str, Any]:
    return _phase(runtime, _phase(runtime, plan, "review", "checker"), "post", "poster")


def _balance(runtime: ReceiptRuntime, order: dict[str, Any]) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).balance(order["id"], SCOPE, actor=actor)


@pytest.mark.parametrize("foreign", [False, True], ids=["identity", "foreign"])
def test_actual_credit_second_collection_partial_refund_inverse_and_final_settlement(receipt_database: tuple[str, str], foreign: bool) -> None:
    runtime, order = _source(receipt_database, foreign=foreign)
    order = _collect(runtime, order, 4000, rate="1.30" if foreign else None, number="CASH-FIRST")
    _posted(runtime, _return(runtime, order, 6, 1))
    balance = _balance(runtime, order)
    assert (balance["transaction_outstanding_minor"], balance["functional_outstanding_minor"]) == ("560", "700" if foreign else "560")
    # This second REAL collection follows a posted credit. Original gross minus
    # only collections is not its current receivable carrying basis.
    order = _collect(runtime, order, 560, rate="1.30" if foreign else None, number="CASH-AFTER-CREDIT")
    returned = _posted(runtime, _return(runtime, order, 4, 3))
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant)
        refund = owner.prepare_refund(MonetaryPartialRefundPreparation(returned["id"], 1500, "period", DAY,
            HistoricalRate("1.20", "Synthetic refund spot", DAY + "T12:00:00Z") if foreign else None,
            "Actual partial refund", 4), command_id="refund:first", actor=actor)
    refund = _posted(runtime, refund)
    with runtime.actor("maker") as (connection, _, actor):
        inverse = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).prepare_reversal(
            MonetaryPartialReversePreparation(refund["id"], "period", DAY, "Actual exact refund inverse", 5),
            command_id="refund:inverse", actor=actor)
    _posted(runtime, inverse)
    with runtime.actor("maker") as (connection, _, actor):
        refund = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).prepare_refund(
            MonetaryPartialRefundPreparation(returned["id"], 4560, "period", DAY,
                HistoricalRate("1.20", "Synthetic final refund spot", DAY + "T12:00:00Z") if foreign else None,
                "Actual final customer settlement", 6), command_id="refund:final", actor=actor)
    _posted(runtime, refund)
    balance = _balance(runtime, order)
    assert balance["history_version"] == 7
    for field in ("transaction_outstanding_minor", "functional_outstanding_minor", "transaction_refund_due_minor", "functional_refund_due_minor"):
        assert balance[field] == "0"
    assert balance["active_plan_id"] is balance["active_revaluation_plan_id"] is None
    with runtime.actor("poster") as (connection, _, _actor):
        invoice = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(order["invoice_id"])
        assert invoice["outstanding_minor"] == 0 and invoice["status"] == "Paid"
        layer = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        assert dict(layer) == {"remaining_quantity_scaled": 10, "remaining_value_minor": 12000}
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_history WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 7
    # Independent rational cash difference: collected4560 at1.30, refunded4560
    # at1.20; no SUT conversion or allocation helper determines this expectation.
    gain = int(Fraction(4560) * (Fraction("1.30") - Fraction("1.20"))) if foreign else 0
    balances = native_balances(runtime)
    assert balances["INVENTORY"] == 12000 and balances["CLEARING"] == -12000
    assert balances["CASH"] == gain and balances.get("GAIN", 0) == -gain
    assert all(value == 0 for account, value in balances.items() if account not in {"INVENTORY", "CLEARING", "CASH", "GAIN"})


def test_actual_zero_functional_collection_keeps_positive_transaction_cash_without_a_fake_entry(receipt_database: tuple[str, str]) -> None:
    runtime, order = _source(receipt_database, foreign=True, unit_price=1, original_rate="0.25")
    with runtime.actor("poster") as (connection, _, _actor):
        before = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
    order = _collect(runtime, order, 1, rate="0.01", number="ZERO-FUNCTIONAL-CASH")
    with runtime.actor("poster") as (connection, _, _actor):
        plan = connection.execute("SELECT entry_id,payload FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, order["collection_plan_id"])).fetchone()
        assert plan["entry_id"] is None and plan["payload"]["snapshot"] is None and plan["payload"]["validation_digest"] is None
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == before
        receipt = connection.execute("SELECT amount_minor,status FROM reconforge.ar_receipts WHERE tenant_id=%s AND id=%s", (runtime.tenant, order["receipt_id"])).fetchone()
        assert dict(receipt) == {"amount_minor": 1, "status": "Posted"}
    balance = _balance(runtime, order)
    assert balance["transaction_collected_minor"] == "1" and balance["history_version"] == 1
    assert balance["functional_outstanding_minor"] == "3"
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError):
        # The fixed zero case never authorizes omission on a general FX source.
        from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
        PostgresOperationalFxTaxRepository(connection, runtime.tenant)._admit_journal_presence({}, {"entry_id": None})
