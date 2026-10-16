"""Actual149 commands; no synthetic journal insertion or mocked source owner.

The dedicated PostgreSQL gate supplies the owned ordinary-role fixture. Missing
native configuration fails that gate; this module adds no skip/xfail path.
Independent raw91 qualification is separate from these business regressions.
"""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from reconforge.domain.inventory_transfer import PERMISSIONS as TRANSFER_PERMISSIONS
from reconforge.domain.inventory_transfer import TransferInversePreparation, TransferPreparation
from reconforge.domain.monetary_customer_partial_return_commands import (
    MonetaryPartialRefundPreparation,
    MonetaryPartialReturnPreparation,
    MonetaryPartialReversePreparation,
)
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)
from reconforge.infrastructure.postgres_monetary_stock_sales import PostgresMonetaryStockSalesRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.monetary_capture_encoding import encode_monetary_capture
from tests.test_postgres_customer_returns import configure_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database
from tests.test_postgres_inventory_receipt_posting import request as receipt_request
from tests.test_postgres_inventory_transfer import phase as transfer_phase
from tests.test_postgres_inventory_transfer import physical as transfer_physical
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
            original_rate: str = "1.25", receipt_total_minor: int = 12000, fractional: bool = False) -> tuple[ReceiptRuntime, dict[str, Any]]:
    assert type(receipt_total_minor) is int and receipt_total_minor > 0
    assert type(fractional) is bool
    if fractional:
        # Configure the existing unreferenced master before any receipt/Stock
        # history, using the already-supported native tenths fixture pattern.
        base = create_receipt_runtime(database)
        with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
            inventory = PostgresInventoryCoreRepository(connection, base.tenant)
            inventory.upsert_uom(uom_code="TENTH", name="Exact monetary tenths", decimal_places=1, workspace="work")
            inventory.upsert_item(item_code="ITEM", name="Original fractional monetary item", organization_code="ORG", uom_code="TENTH",
                                  inventory_account_code="INVENTORY", workspace="work")
        runtime = create_stock_runtime(database, base_runtime=base, seed_stock=False)
    else:
        runtime = create_stock_runtime(database, seed_stock=receipt_total_minor == 12000)
    configure_runtime(runtime)
    quantity = "1" if fractional else "10"
    if receipt_total_minor != 12000 or fractional:
        with runtime.actor("maker") as (_, owner, actor):
            receipt = owner.prepare_receipt(replace(receipt_request(), quantity=quantity, total_value_minor=receipt_total_minor),
                command_id="inbound-prepare", actor=actor)
        with runtime.actor("checker") as (_, owner, actor):
            review = owner.review(receipt["plan_id"], command_id="inbound-review", expected_plan_digest=receipt["plan_digest"],
                reason="Independent exact small original FIFO cost", actor=actor)
        with runtime.actor("poster") as (_, owner, actor):
            owner.commit(receipt["plan_id"], command_id="inbound-commit", expected_review_digest=review["review_digest"],
                reason="Publish genuine positive original cost", actor=actor)
    seed_fx_masters(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        order = _stock(connection, runtime).create(StockOrder("ACTUAL-MONETARY", "FOREIGN" if foreign else "CUSTOMER",
            "SOURCE-PO", "ITEM", "MAIN", "STOCK", quantity, unit_price, "EUR" if foreign else "USD", DAY,
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
        "receipt_number": number, "receipt_date": DAY, "period_id": "period",
        "amount_minor": amount, "settlement_rate": _rate(rate)}, suffix=number)
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


def test_actual_monetary_reads_preserve_all_91_original_tables_and_current_authority(receipt_database: tuple[str, str]) -> None:
    from psycopg import sql

    from tests.customer_partial_return_monetary_posted_oracle import TABLES

    runtime, order = _source(receipt_database, foreign=True)
    with runtime.actor("maker") as (connection, _, actor):
        flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
        assert flags is not None and all(type(flags[name]) is bool and not flags[name]
            for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication"))
        assert len(TABLES) == len(set(TABLES)) == 91
        secured = connection.execute("""SELECT count(*) n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity
            AND c.relowner<>current_user::regrole""", (list(TABLES),)).fetchone()
        assert secured["n"] == 91

        def originals() -> dict[str, list[str]]:
            result = {}
            for name in TABLES:
                rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text LIMIT 4097")
                    .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
                assert len(rows) <= 4096
                result[name] = [row["original"] for row in rows]
            return result

        def unchanged(before: dict[str, list[str]]) -> None:
            after = originals()
            # Failure output identifies only table names, never original rows.
            changed_tables = [name for name in TABLES if before[name] != after[name]]
            assert not changed_tables

        partial = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant)
        stock = _stock(connection, runtime)
        for _ in range(2):
            before = originals()
            balance = partial.balance(order["id"], SCOPE, actor=actor)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            unchanged(before)
            assert (balance["history_version"], balance["transaction_outstanding_minor"], balance["functional_outstanding_minor"]) == (0, "11400", "14250")
            before = originals()
            assert stock.get(order["id"], actor=actor) == order
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            unchanged(before)

        outside = {**SCOPE, "workspace_id": "outside"}
        before = originals()
        with pytest.raises(FinancePostingError) as wrong_partial_scope:
            partial.balance(order["id"], outside, actor=actor)
        assert wrong_partial_scope.value.code == "operational_scope_denied"
        unchanged(before)
        with pytest.raises(FinancePostingError) as wrong_stock_scope:
            PostgresMonetaryStockSalesRepository(connection, runtime.tenant, **outside,
                organization_code="ORG", entity_code="ENTITY").get(order["id"], actor=actor)
        assert wrong_stock_scope.value.code == "sales_scope_denied"
        unchanged(before)

        # Keep the authenticated principal and actor stale while withdrawing
        # the persisted permission; the read must still check current authority.
        with connection.transaction(force_rollback=True):
            changed = connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by=%s,
                revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1
                WHERE tenant_id=%s AND permission_name='finance_core.read' RETURNING permission_name""", (actor.user_id, runtime.tenant)).fetchall()
            assert changed
            before = originals()
            with pytest.raises(FinancePostingError) as partial_permission:
                partial.balance(order["id"], SCOPE, actor=actor)
            assert partial_permission.value.code == "operational_actor_denied"
            unchanged(before)
            with pytest.raises(FinancePostingError) as stock_permission:
                stock.get(order["id"], actor=actor)
            assert stock_permission.value.code == "sales_actor_denied"
            unchanged(before)


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
        assert order["monetary_origin"]["invoice_id"]
        invoice = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(order["monetary_origin"]["invoice_id"])
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
        plan = connection.execute("SELECT source_id,entry_id,payload FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, order["collection"]["id"])).fetchone()
        assert plan["source_id"] == order["monetary_origin"]["fx_source_id"]
        assert plan["entry_id"] is None and plan["payload"]["snapshot"] is None and plan["payload"]["validation_digest"] is None
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == before
        receipt = connection.execute("SELECT amount_minor,status FROM reconforge.ar_receipts WHERE tenant_id=%s AND id=%s", (runtime.tenant, order["collection"]["receipt_id"])).fetchone()
        assert dict(receipt) == {"amount_minor": 1, "status": "Posted"}
    balance = _balance(runtime, order)
    assert balance["transaction_collected_minor"] == "1" and balance["history_version"] == 1
    assert balance["functional_outstanding_minor"] == "3"
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError):
        # The fixed zero case never authorizes omission on a general FX source.
        from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
        PostgresOperationalFxTaxRepository(connection, runtime.tenant)._admit_journal_presence({}, {"entry_id": None})


def test_actual_zero_journal_return_cancel_and_exact_merchandise_inverse_keep_physical_governance(receipt_database: tuple[str, str]) -> None:
    runtime, order = _source(receipt_database, foreign=True, unit_price=10, original_rate="0.25", receipt_total_minor=1, fractional=True)

    def check_stage(version: int, restored_quantity: int, restoration_rows: int) -> None:
        # Original receipt1 + COGS1 + recognition3. No Return/Inverse can
        # fabricate an entry for zero L credit and zero apportioned L cost.
        balances = native_balances(runtime)
        assert {key: value for key, value in balances.items() if value} == {"CLEARING": -1, "COGS": 1, "AR": 3, "REVENUE": -3}
        with runtime.actor("poster") as (connection, _, _actor):
            stock = connection.execute("SELECT quantity_scaled,quantity_precision FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
                                       (runtime.tenant, order["id"])).fetchone()
            assert dict(stock) == {"quantity_scaled": 10, "quantity_precision": 1}
            assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 3
            assert connection.execute("SELECT count(*) n FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 3
            assert connection.execute("SELECT count(*) n FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 6
            totals = connection.execute("SELECT COALESCE(sum(debit_minor),0) dr,COALESCE(sum(credit_minor),0) cr "
                                        "FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
            assert dict(totals) == {"dr": 5, "cr": 5}
            assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_entries WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
            layer = connection.execute("SELECT original_quantity_scaled,original_value_minor,remaining_quantity_scaled,remaining_value_minor "
                                       "FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
            assert len(layer) == 1 and dict(layer[0]) == {"original_quantity_scaled": 10, "original_value_minor": 1,
                "remaining_quantity_scaled": restored_quantity, "remaining_value_minor": 0}
            assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_history WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == version
            assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == restoration_rows
        balance = _balance(runtime, order)
        assert balance["history_version"] == version and balance["remaining_quantity_scaled"] == str(10 - restored_quantity)
        assert balance["transaction_outstanding_minor"] == str(11 - restored_quantity) and balance["functional_outstanding_minor"] == "3"
        assert balance["transaction_refund_due_minor"] == balance["functional_refund_due_minor"] == "0"

    def prepare(command: str) -> dict[str, Any]:
        args = MonetaryPartialReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY", source_order_id=order["id"],
            quantity_scaled=1, period_id="period", posting_date=DAY, reason="Actual zero functional credit and FIFO portion", expected_history_version=0)
        with runtime.actor("maker") as (connection, _, actor):
            owner = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant)
            result = owner.prepare(args, command_id=command, actor=actor)
            assert owner.prepare(args, command_id=command, actor=actor) == result
            assert result["entries"] == [] and result["quantity_scaled"] == "1"
            assert (result["monetary"]["transaction_credit_minor"], result["monetary"]["functional_credit_minor"],
                    result["monetary"]["functional_cost_minor"], result["monetary"]["functional_turnover_minor"]) == ("1", "0", "0", "0")
            return result

    check_stage(0, 0, 0)
    cancelled = prepare("zero-return:cancelled-prepare")
    with pytest.raises(FinancePostingError) as self_cancel:
        _phase(runtime, cancelled, "cancel", "maker")
    assert self_cancel.value.code == "monetary_return_phase_denied"
    check_stage(0, 0, 0)
    cancelled = _phase(runtime, cancelled, "cancel", "checker")
    assert cancelled["phase"] == 3 and cancelled["status"] == "Cancelled" and cancelled["entries"] == []
    check_stage(0, 0, 0)

    posted = _posted(runtime, prepare("zero-return:fresh-prepare"))
    assert posted["phase"] == 2 and posted["entries"] == [] and posted["movement_id"]
    assert len({posted["preparer_actor_id"], posted["reviewer_actor_id"], posted["posted_actor_id"]}) == 3
    check_stage(1, 1, 1)
    with runtime.actor("poster") as (connection, _, _actor):
        restoration = connection.execute("SELECT quantity_scaled,value_minor,direction,correction_effect_id,physical_movement_id "
            "FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, posted["id"])).fetchone()
        assert dict(restoration) == {"quantity_scaled": 1, "value_minor": 0, "direction": 1, "correction_effect_id": None, "physical_movement_id": posted["movement_id"]}
        movement = connection.execute("SELECT movement_type,status,source_reference FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s",
                                      (runtime.tenant, posted["movement_id"])).fetchone()
        assert dict(movement) == {"movement_type": "Receipt", "status": "Posted", "source_reference": posted["id"]}
        detail = connection.execute("SELECT quantity_scaled,quantity_precision FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id=%s",
                                    (runtime.tenant, posted["movement_id"])).fetchall()
        assert len(detail) == 1 and dict(detail[0]) == {"quantity_scaled": 1, "quantity_precision": 1}
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant)
        args = MonetaryPartialReversePreparation(posted["id"], "period", DAY, "Reverse exact zero functional merchandise operation", 1)
        inverse = owner.prepare_reversal(args, command_id="zero-return:inverse-prepare", actor=actor)
        assert owner.prepare_reversal(args, command_id="zero-return:inverse-prepare", actor=actor) == inverse
    inverse = _posted(runtime, inverse)
    assert inverse["entries"] == [] and inverse["operation"] == "ReverseReturn" and inverse["original_id"] == posted["id"]
    assert len({inverse["preparer_actor_id"], inverse["reviewer_actor_id"], inverse["posted_actor_id"]}) == 3
    check_stage(2, 0, 2)
    with runtime.actor("poster") as (connection, _, _actor):
        rows = connection.execute("SELECT direction,quantity_scaled,value_minor,correction_effect_id,original_restoration_plan_id "
            "FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, inverse["id"])).fetchall()
        assert len(rows) == 1 and dict(rows[0]) == {"direction": -1, "quantity_scaled": 1, "value_minor": 0,
            "correction_effect_id": None, "original_restoration_plan_id": posted["id"]}
        movement = connection.execute("SELECT movement_type,status,source_reference FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s",
                                      (runtime.tenant, inverse["movement_id"])).fetchone()
        assert dict(movement) == {"movement_type": "Delivery", "status": "Posted", "source_reference": inverse["id"]}
        detail = connection.execute("SELECT quantity_scaled,quantity_precision FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id=%s",
                                    (runtime.tenant, inverse["movement_id"])).fetchall()
        assert len(detail) == 1 and dict(detail[0]) == {"quantity_scaled": 1, "quantity_precision": 1}


def test_actual_cr3_zero_cost_restoration_resale_return_and_it1_transfer_keep_original_lineage(receipt_database: tuple[str, str]) -> None:
    from psycopg import sql

    from tests.customer_partial_return_monetary_posted_oracle import TABLES

    destination = os.environ.get("RECONFORGE_PARTIAL_REMAINDER_PRIVATE_OUTPUT")
    private = Path(destination) if destination else None
    if private is not None:
        if not private.is_absolute() or not private.is_dir():
            raise AssertionError("An explicit existing private custody directory is required.")
        for candidate in (private, *private.parents):
            if candidate.is_symlink() or getattr(candidate.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise AssertionError("Private custody ancestry must remain owned and unlinked.")
    runtime, original = _source(receipt_database, foreign=True, unit_price=10, original_rate="0.25", receipt_total_minor=1, fractional=True)
    captures: list[dict[str, Any]] = []
    source_ids = [original["id"]]

    def capture(checkpoint: str) -> None:
        if private is None:
            return
        with runtime.actor("poster") as (connection, _, _actor):
            flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
            assert flags is not None and all(type(flags[name]) is bool and not flags[name]
                for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication"))
            assert len(TABLES) == len(set(TABLES)) == 91
            secured = connection.execute("""SELECT count(*) n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity
                AND c.relowner<>current_user::regrole""", (list(TABLES),)).fetchone()
            assert secured["n"] == 91
            parents = connection.execute("SELECT id,customer_id,invoice_id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=ANY(%s)",
                                         (runtime.tenant, source_ids)).fetchall()
            assert len(parents) == len(source_ids)
            for table, column in (("ar_customers", "customer_id"), ("ar_invoices", "invoice_id"), ("stock_sales_orders", "id")):
                for identifier in sorted({row[column] for row in parents if row[column] is not None}):
                    held = connection.execute(sql.SQL("SELECT id FROM reconforge.{} WHERE tenant_id=%s AND id=%s FOR SHARE")
                        .format(sql.Identifier(table)), (runtime.tenant, identifier)).fetchall()
                    assert len(held) == 1
            assert len(connection.execute("SELECT tenant_id FROM reconforge.domain_audit_ledger_state WHERE tenant_id=%s FOR SHARE", (runtime.tenant,)).fetchall()) == 1
            tables = {}
            for name in TABLES:
                rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text LIMIT 4097")
                    .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
                assert len(rows) <= 4096
                tables[name] = [row["original"] for row in rows]
            value = {"checkpoint": checkpoint, "tables": tables}
            encode_monetary_capture(value)
            captures.append(value)

    def finance(effects: int, lines: int, turnover: int) -> None:
        with runtime.actor("poster") as (connection, _, _actor):
            totals = connection.execute("""SELECT count(DISTINCT e.id) effects,count(l.id) lines,
                sum(l.debit_minor) debit,sum(l.credit_minor) credit FROM reconforge.finance_posting_effects e
                JOIN reconforge.finance_entry_lines l ON(l.tenant_id,l.entry_id)=(e.tenant_id,e.entry_id)
                WHERE e.tenant_id=%s""", (runtime.tenant,)).fetchone()
            assert dict(totals) == {"effects": effects, "lines": lines, "debit": turnover, "credit": turnover}

    def retained_originals() -> tuple[str, str]:
        with runtime.actor("poster") as (connection, _, _actor):
            consumed = connection.execute("""SELECT to_jsonb(c)::text original FROM reconforge.inventory_layer_consumptions c
                JOIN reconforge.inventory_valuation_lines v ON(v.tenant_id,v.id)=(c.tenant_id,c.valuation_line_id)
                WHERE c.tenant_id=%s AND v.valuation_document_id=%s""", (runtime.tenant, original["valuation_id"])).fetchall()
            history = connection.execute("""SELECT to_jsonb(h)::text original FROM reconforge.customer_partial_return_monetary_history h
                JOIN reconforge.stock_sales_monetary_origins o ON(o.tenant_id,o.id)=(h.tenant_id,h.origin_id)
                WHERE h.tenant_id=%s AND o.stock_order_id=%s ORDER BY h.sequence""", (runtime.tenant, original["id"])).fetchall()
            assert len(consumed) == len(history) == 1
            return consumed[0]["original"], history[0]["original"]

    finance(3, 6, 5)
    capture("Original")
    old_return = _posted(runtime, _return(runtime, original, 1, 0))
    assert old_return["entries"] == [] and old_return["movement_id"]
    assert (old_return["monetary"]["transaction_credit_minor"], old_return["monetary"]["functional_credit_minor"],
            old_return["monetary"]["functional_cost_minor"]) == ("1", "0", "0")
    frozen_originals = retained_originals()
    finance(3, 6, 5)
    capture("OldZeroReturn")

    # This is a new fixed monetary Stock source, not a synthetic zero journal
    # or a repricing of the original EUR commercial line.
    with runtime.actor("maker") as (connection, _, actor):
        resale = _stock(connection, runtime).create(StockOrder("CR3-ZERO-RESALE", "CUSTOMER", "RESTORED-PO", "ITEM", "MAIN", "STOCK",
            "0.1", 1000, "USD", DAY, "Actual resale of CR3-restored zero-cost quantity"), command_id="cr3-zero-resale:create", actor=actor)
    for operation, human, parameters in (
        ("submit", "maker", {}), ("approve", "checker", {}), ("reserve", "maker", {}),
        ("prepare-issue", "maker", {"posting_date": DAY, "period_id": "period", "policy_code": "FIFO"}),
        ("review-issue", "checker", {}), ("deliver", "poster", {}),
        ("prepare-invoice", "maker", {"invoice_number": "CR3-ZERO-RESALE-INVOICE", "invoice_date": DAY, "due_date": "2026-10-31",
            "journal_code": "STOCK", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE",
            "cash_account_code": "CASH", "refund_liability_account_code": "REFUND", "gain_account_code": "GAIN", "loss_account_code": "LOSS",
            "country_code": "EG", "transaction_class": "synthetic-stock", "original_rate": None,
            "taxes": [{"policy_id": "SYNTHETIC-VAT", "country_code": "EG", "transaction_class": "synthetic-stock",
                "effective_from": "2026-01-01", "effective_to": "2026-12-31", "rate": "0.14", "account_code": "TAX",
                "source": "Synthetic reviewed fraction", "version": "2026-v1"}]}),
        ("review-invoice", "checker", {}), ("invoice", "poster", {}),
    ):
        resale = _act(runtime, resale, operation, human, parameters)
    assert resale["status"] == "Invoiced" and resale["quantity_scaled"] == "1" and resale["quantity_precision"] == 1
    assert resale["functional_cogs_minor"] == "0" and resale["cogs_entry_id"] is resale["cogs_effect_id"] is None
    assert resale["cost_admission_policy"] == "partial-return-restituted-v1" and resale["movement_id"] and resale["valuation_id"]
    origin = resale["monetary_origin"]
    assert origin["original_rate"] is None
    assert tuple(origin[key] for key in ("transaction_net_minor", "transaction_tax_minor", "transaction_gross_minor",
        "functional_net_minor", "functional_tax_minor", "functional_gross_minor")) == ("100", "14", "114", "100", "14", "114")
    finance(4, 9, 119)
    assert retained_originals() == frozen_originals
    source_ids.append(resale["id"])
    capture("ResaleInvoiced")

    with runtime.actor("maker") as (connection, _, actor):
        request = MonetaryPartialReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY", source_order_id=resale["id"],
            quantity_scaled=1, period_id="period", posting_date=DAY, reason="Actual full return of zero-cost resale", expected_history_version=0)
        owner = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant)
        returned = owner.prepare(request, command_id="cr3-zero-resale:return", actor=actor)
        assert owner.prepare(request, command_id="cr3-zero-resale:return", actor=actor) == returned
    returned = _posted(runtime, returned)
    assert [part["purpose"] for part in returned["entries"]] == ["MerchandiseCredit"]
    assert (returned["monetary"]["transaction_credit_minor"], returned["monetary"]["functional_credit_minor"],
            returned["monetary"]["functional_cost_minor"]) == ("114", "114", "0")
    for plan in (old_return, returned):
        assert len({plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]}) == 3
    finance(5, 12, 233)
    assert retained_originals() == frozen_originals
    capture("ResaleReturned")

    with runtime.actor("poster") as (connection, _, _actor):
        consumed = connection.execute("""SELECT c.* FROM reconforge.inventory_layer_consumptions c
            JOIN reconforge.inventory_valuation_lines v ON(v.tenant_id,v.id)=(c.tenant_id,c.valuation_line_id)
            WHERE c.tenant_id=%s ORDER BY c.value_minor DESC,c.id""", (runtime.tenant,)).fetchall()
        assert [(row["quantity_scaled"], row["value_minor"]) for row in consumed] == [(10, 1), (1, 0)]
        item = connection.execute("SELECT item_id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s", (runtime.tenant, original["id"])).fetchone()["item_id"]
        source = connection.execute("SELECT payload,source_digest FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=%s AND stock_order_id=%s",
                                    (runtime.tenant, resale["id"])).fetchone()
        issue = connection.execute("SELECT issue_plan,reconforge.irp_digest(issue_plan) digest FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
                                   (runtime.tenant, resale["id"])).fetchone()
        assert source["payload"]["source"]["original_cost_admission_digest"] == issue["digest"]
        assert source["payload"]["source"]["consumptions"][0]["original_consumption_id"] == consumed[1]["id"]
        assert source["payload"]["source"]["consumptions"][0]["value_minor"] == 0
        document = connection.execute("SELECT status,total_value_minor,finance_entry_id FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND id=%s",
                                      (runtime.tenant, resale["valuation_id"])).fetchone()
        assert dict(document) == {"status": "Approved", "total_value_minor": 0, "finance_entry_id": None}
        restorations = connection.execute("""SELECT plan_id,quantity_scaled,value_minor,direction,correction_effect_id,consumption_count_at_restore
            FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=%s ORDER BY consumption_count_at_restore""", (runtime.tenant,)).fetchall()
        assert [dict(row) for row in restorations] == [
            {"plan_id": old_return["id"], "quantity_scaled": 1, "value_minor": 0, "direction": 1, "correction_effect_id": None, "consumption_count_at_restore": 1},
            {"plan_id": returned["id"], "quantity_scaled": 1, "value_minor": 0, "direction": 1, "correction_effect_id": None, "consumption_count_at_restore": 2},
        ]
        pool = connection.execute("SELECT reconforge.it1_cost_snapshot(%s,'work','org','entity',%s) value", (runtime.tenant, item)).fetchone()["value"]
        assert pool["schema_version"] == "inventory-transfer-cost-v4" and pool["remaining_quantity_scaled"] == 1 and pool["remaining_value_minor"] == 0
        assert len(pool["sources"]) == 1 and pool["sources"][0]["partial_return_corrections"] == []
        assert {part["restoration"]["plan_id"] for part in pool["sources"][0]["monetary_return_corrections"]} == {old_return["id"], returned["id"]}
        admissions = pool["sources"][0]["restituted_consumption_admissions"]
        assert len(admissions) == 1 and admissions[0]["consumption_id"] == consumed[1]["id"] and admissions[0]["posting_effect"] is None
        connection.execute("SELECT reconforge.it1_cost_originals(%s,%s::jsonb)", (runtime.tenant, canonical_json(pool)))

    # The transfer follows the zero-cost resale AND its new return. Its
    # authority must admit the genuine absent-journal consumed document too.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*TRANSFER_PERMISSIONS.values())):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        inventory = PostgresInventoryCoreRepository(connection, runtime.tenant)
        inventory.upsert_warehouse(warehouse_code="SECOND", name="Restituted destination", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="SECOND", location_code="STOCK", name="Restituted stock", organization_code="ORG", workspace="work")
    with runtime.actor("maker") as (connection, _, actor):
        transfer_owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        with pytest.raises(FinancePostingError) as wrong_currency:
            transfer_owner._consumed_document_amount({**pool, "monetary_policy": {**pool["monetary_policy"], "currency_code": "EUR"}}, SCOPE)
        assert wrong_currency.value.code == "inventory_transfer_invalid"
        transfer = transfer_owner.create(TransferPreparation("CR3-ZERO-TRANSFER", "ITEM", "0.1",
            "MAIN/STOCK", "SECOND/STOCK", "period", DAY, "Actual transfer after zero-cost resale return", SCOPE), command_id="cr3-zero-transfer:create", actor=actor)
        assert transfer_physical(connection, runtime) == {"MAIN/STOCK": 1, "SECOND/STOCK": 0}
        assert transfer["source"]["cost_snapshot"] == pool
    transfer = transfer_phase(runtime, transfer_phase(runtime, transfer, "review", "checker"), "post", "poster")
    assert transfer["source"]["phase"] == 2
    capture("TransferPosted")
    with runtime.actor("maker") as (connection, _, actor):
        assert transfer_physical(connection, runtime) == {"MAIN/STOCK": 0, "SECOND/STOCK": 1}
        native = transfer["source"]
        inverse = PostgresInventoryTransferRepository(connection, runtime.tenant).create_inverse(TransferInversePreparation(native["id"], native["source_digest"],
            native["row_version"], "CR3-ZERO-TRANSFER-INVERSE", "period", DAY, "Exact physical inverse after zero-cost resale"),
            command_id="cr3-zero-transfer:inverse", actor=actor)
    inverse = transfer_phase(runtime, transfer_phase(runtime, inverse, "review", "checker"), "post", "poster")
    assert inverse["source"]["phase"] == 2 and inverse["source"]["original"]["id"] == transfer["source"]["id"]
    capture("TransferInversePosted")
    with runtime.actor("poster") as (connection, _, _actor):
        assert transfer_physical(connection, runtime) == {"MAIN/STOCK": 1, "SECOND/STOCK": 0}
        assert connection.execute("SELECT reconforge.it1_cost_snapshot(%s,'work','org','entity',%s) value", (runtime.tenant, item)).fetchone()["value"] == pool
    finance(5, 12, 233)
    assert retained_originals() == frozen_originals
    assert {key: value for key, value in native_balances(runtime).items() if value} == {"CLEARING": -1, "COGS": 1, "AR": 3, "REVENUE": -3}
    assert _balance(runtime, original)["history_version"] == _balance(runtime, resale)["history_version"] == 1
    assert _balance(runtime, resale)["transaction_outstanding_minor"] == _balance(runtime, resale)["functional_outstanding_minor"] == "0"

    # Later native consumption remains retained even after its own Return.
    # A failed old inverse must not erase that dependency or any business row.
    with runtime.actor("maker") as (connection, _, actor):
        inverse_plan = PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).prepare_reversal(
            MonetaryPartialReversePreparation(old_return["id"], "period", DAY, "Prove retained resale consumption blocks old inverse", 1),
            command_id="cr3-zero-original:inverse", actor=actor)
    inverse_plan = _phase(runtime, inverse_plan, "review", "checker")
    from tests.test_postgres_monetary_customer_return_security import _business_digest

    before = _business_digest(runtime)
    with pytest.raises(FinancePostingError) as dependency:
        _phase(runtime, inverse_plan, "post", "poster")
    assert dependency.value.code == "monetary_return_reversal_dependency" and _business_digest(runtime) == before
    assert _phase(runtime, inverse_plan, "cancel", "poster")["phase"] == 3
    assert retained_originals() == frozen_originals
    finance(5, 12, 233)
    if private is not None:
        assert [value["checkpoint"] for value in captures] == ["Original", "OldZeroReturn", "ResaleInvoiced", "ResaleReturned", "TransferPosted", "TransferInversePosted"]
        packet = {"schema_version": "customer-partial-return-monetary-restituted-cycle-input-v1", "tenant_id": runtime.tenant,
                  "original_source_order_id": original["id"], "resale_source_order_id": resale["id"], "captures": captures}
        encoded = encode_monetary_capture(packet, packet=True)
        with (private / "native-monetary-restituted-cycle-original-v1.json").open("xb") as stream:
            stream.write(encoded)
