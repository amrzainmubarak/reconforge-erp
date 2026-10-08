"""Restricted-role actual purchase-to-stock-to-AP-to-paid-GL cycle."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.procurement_operations import ProcurementPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_payables_payment_link import PostgresPayablesPaymentLinkRepository
from reconforge.infrastructure.postgres_procurement_operations import (
    OPERATIONS,
    PERMISSIONS,
    PostgresProcurementOperationsRepository,
)
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["receipt_database", "pytestmark"]


def seed_procurement(runtime: ReceiptRuntime) -> ReceiptRuntime:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        finance.upsert_account(account_code="AP", name="Accounts payable", account_type="Liability", normal_balance="Credit", chart_code="DEFAULT", workspace="work")
        finance.upsert_account(account_code="CASH", name="Cash", account_type="Asset", chart_code="DEFAULT", workspace="work")
        PostgresPayablesRepository(connection, runtime.tenant).upsert_supplier(supplier_code="SUP", name="Synthetic supplier", currency_code="USD",
            organization_code="ORG", entity_code="ENTITY", workspace="work", actor_label="maker")
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(frozenset().union(*PERMISSIONS.values(), {"payables.read"})):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    return runtime


def create_procurement_runtime(receipt_database: tuple[str, str], base_runtime: ReceiptRuntime | None = None) -> ReceiptRuntime:
    return seed_procurement(base_runtime or create_receipt_runtime(receipt_database))


@pytest.fixture
def procurement_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_procurement_runtime(receipt_database)


def request(number: str = "PO-1") -> ProcurementPreparation:
    return ProcurementPreparation(number=number, supplier_code="SUP", item_code="ITEM", quantity="10", unit_price_minor=1200,
        currency_code="USD", posting_date="2026-10-03", period_id="period", location_code="MAIN/STOCK", policy_code="FIFO",
        journal_code="STOCK", ap_account_code="AP", cash_account_code="CASH", organization_code="ORG", entity_code="ENTITY", workspace="work")


def create(runtime: ReceiptRuntime, number: str = "PO-1") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {"rolsuper": False, "rolbypassrls": False}
        return PostgresProcurementOperationsRepository(connection, runtime.tenant).create(request(number), command_id="create-" + number, actor=actor)


ACTORS = ("maker", "checker", "maker", "checker", "poster", "maker", "checker", "maker", "checker", "poster", "maker", "checker", "poster")


def advance(runtime: ReceiptRuntime, view: dict[str, Any], stop: int = 13) -> dict[str, Any]:
    for index in range(view["cycle"]["row_version"] - 1, stop):
        with runtime.actor(ACTORS[index]) as (connection, _, actor):
            repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
            arguments = {"expected_version": view["cycle"]["row_version"], "command_id": "command-" + str(index), "reason": "Synthetic independent control", "actor": actor}
            view = repository.act(view["cycle"]["id"], OPERATIONS[index], **arguments)
            assert repository.act(view["cycle"]["id"], OPERATIONS[index], **arguments) == view
    return view


def complete_procurement_cycle(runtime: ReceiptRuntime, number: str = "PO-1") -> dict[str, Any]:
    return advance(runtime, create(runtime, number))


def test_options_are_named_json_serializable_scoped_and_bounded(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    with runtime.actor("maker") as (connection, _, actor):
        suppliers = PostgresPayablesRepository(connection, runtime.tenant)
        for index in range(201):
            suppliers.upsert_supplier(supplier_code=f"Z-{index:03d}", name=f"Synthetic vendor {index}", currency_code="USD",
                workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
        value = PostgresProcurementOperationsRepository(connection, runtime.tenant).options("work", "ORG", "ENTITY", actor=actor)
        response = json.loads(json.dumps(value))
        assert set(response) == {"suppliers", "items", "locations", "policies", "periods", "journals", "accounts"}
        assert len(response["suppliers"]) == 200
        assert all(isinstance(row, dict) for rows in response.values() for row in rows)
        assert all(len(rows) <= 200 for rows in response.values())
        assert response["suppliers"][0] == {"code": "SUP", "name": "Synthetic supplier", "currency_code": "USD"}
        assert response["items"][0]["code"] == "ITEM" and response["locations"][0]["code"] == "MAIN/STOCK"
        assert response["policies"][0] == {"code": "FIFO", "currency_code": "USD"}
        assert response["periods"] == [{"id": "period", "name": "2026-10", "start_date": "2026-10-01", "end_date": "2026-10-31"}]
        assert response["journals"][0]["code"] == "STOCK" and response["journals"][0]["chart_code"] == "DEFAULT"
        assert {row["code"] for row in response["accounts"]} >= {"AP", "CASH"}
        assert all(row["chart_code"] == "DEFAULT" for row in response["accounts"])


def test_options_exclude_accounts_without_reviewed_manual_posting_authority(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    with runtime.actor("maker") as (connection, _, actor):
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        finance.upsert_account(account_code="BLOCKED", name="Synthetic blocked manual account", account_type="Liability",
            normal_balance="Credit", chart_code="DEFAULT", workspace="work", allow_manual_posting=False)
        finance.upsert_account(account_code="INACTIVE", name="Synthetic inactive account", account_type="Asset",
            chart_code="DEFAULT", workspace="work", active=False)
        value = PostgresProcurementOperationsRepository(connection, runtime.tenant).options("work", "ORG", "ENTITY", actor=actor)
        codes = {row["code"] for row in value["accounts"]}
        assert {"BLOCKED", "INACTIVE"}.isdisjoint(codes) and {"AP", "CASH"} <= codes


def test_actual_full_cycle_has_fifo_stock_cleared_accrual_paid_ap_and_exact_gl(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    view = complete_procurement_cycle(runtime)
    assert view["cycle"]["stage"] == "Paid" and view["cycle"]["total_minor"] == "12000"
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
        assert repository.get(view["cycle"]["id"], actor=actor) == view
        invoice = PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(view["cycle"]["invoice_id"])
        assert invoice["status"] == "Paid"
        layers = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        assert [dict(layer) for layer in layers] == [{"remaining_quantity_scaled": 10, "remaining_value_minor": 12000}]
        effects = connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        assert effects["n"] == 3
        balances = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS balance
            FROM reconforge.finance_entry_lines l JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            JOIN reconforge.finance_posting_effects e ON e.tenant_id=l.tenant_id AND e.entry_id=l.entry_id WHERE l.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        assert {row["account_code"]: int(row["balance"]) for row in balances} == {"INVENTORY": 12000, "CLEARING": 0, "AP": 0, "CASH": -12000}
        assert connection.execute("SELECT count(*) AS n FROM reconforge.procurement_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 14


def test_same_actor_order_approval_and_altered_replay_are_denied(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=1)
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
        with pytest.raises(Exception, match="Separation of duties"):
            repository.act(view["cycle"]["id"], "approve-order", expected_version=2, command_id="bad-approve", reason="Invalid self approval", actor=actor)
        with pytest.raises(FinancePostingError, match="exact request"):
            repository.create(replace(request(), unit_price_minor=1201), command_id="create-PO-1", actor=actor)
        assert repository.get(view["cycle"]["id"], actor=actor)["cycle"]["stage"] == "Submitted"


def test_receiving_late_ap_failure_rolls_back_stock_fifo_gl_and_then_safe_retry(procurement_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=4)
    original = PostgresPayablesRepository.post_receipt
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Synthetic late AP receipt failure")
    monkeypatch.setattr(PostgresPayablesRepository, "post_receipt", fail)
    with runtime.actor("poster") as (connection, _, actor):
        with pytest.raises(RuntimeError, match="late AP"):
            PostgresProcurementOperationsRepository(connection, runtime.tenant).act(view["cycle"]["id"], "receive", expected_version=5, command_id="receive-fail", reason="Synthetic receipt", actor=actor)
        for table in ("inventory_movements", "inventory_cost_layers", "finance_posting_effects", "ap_goods_receipts"):
            assert connection.execute("SELECT count(*) AS n FROM reconforge." + table + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    monkeypatch.setattr(PostgresPayablesRepository, "post_receipt", original)
    assert advance(runtime, view, stop=5)["cycle"]["stage"] == "Received"


def test_payment_late_settlement_failure_keeps_invoice_unpaid_and_rolls_back_new_gl(procurement_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=12)
    original = PostgresPayablesPaymentLinkRepository.link_finance_payment
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Synthetic late settlement failure")
    monkeypatch.setattr(PostgresPayablesPaymentLinkRepository, "link_finance_payment", fail)
    with runtime.actor("poster") as (connection, _, actor):
        with pytest.raises(RuntimeError, match="late settlement"):
            PostgresProcurementOperationsRepository(connection, runtime.tenant).act(view["cycle"]["id"], "pay", expected_version=13, command_id="payment-fail", reason="Synthetic payment", actor=actor)
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
        assert PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(view["cycle"]["invoice_id"])["status"] == "Approved"
    monkeypatch.setattr(PostgresPayablesPaymentLinkRepository, "link_finance_payment", original)
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


def test_six_connections_one_create_command_produces_one_po_and_ack(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    with ThreadPoolExecutor(max_workers=6) as pool:
        views = list(pool.map(lambda _: create(runtime, "CONCURRENT"), range(6)))
    assert all(view == views[0] for view in views)
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.procurement_cycles WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM reconforge.ap_purchase_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_raw_stage_without_command_evidence_rolls_back_order_transition(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = procurement_runtime
    view = create(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="exactly one retained command"), runtime.actor("maker") as (connection, _, _actor):
        PostgresPayablesRepository(connection, runtime.tenant).submit_purchase_order(view["cycle"]["purchase_order_id"], expected_version=1, actor_label="maker")
        connection.execute("UPDATE reconforge.procurement_cycles SET stage=1,row_version=2 WHERE tenant_id=%s AND id=%s", (runtime.tenant, view["cycle"]["id"]))
    with runtime.actor("maker") as (connection, _, actor):
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor)["cycle"]["stage"] == "Draft"


def test_retained_po_line_change_and_command_evidence_delete_are_refused(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=5)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.ap_purchase_order_lines SET ordered_quantity=11,ordered_quantity_text='11' WHERE tenant_id=%s AND purchase_order_id=%s", (runtime.tenant, view["cycle"]["purchase_order_id"]))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("DELETE FROM reconforge.procurement_commands WHERE tenant_id=%s AND cycle_id=%s", (runtime.tenant, view["cycle"]["id"]))


def test_real_stock_effect_cannot_be_attached_as_invoice_accrual(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=9)
    with pytest.raises(psycopg.errors.CheckViolation, match="accrual effect must belong"), runtime.actor("poster") as (connection, _, _actor):
        effect = connection.execute("SELECT posting_effect_id FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, view["cycle"]["receipt_plan_id"])).fetchone()["posting_effect_id"]
        connection.execute("UPDATE reconforge.procurement_cycles SET stage=10,row_version=row_version+1,accrual_effect_id=%s WHERE tenant_id=%s AND id=%s", (effect, runtime.tenant, view["cycle"]["id"]))


def test_entity_alias_confusion_hides_both_cycle_and_commands(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    view = create(runtime)
    with runtime.actor("maker") as (connection, _, _actor):
        connection.execute("SELECT set_config('app.entity_id','foreign',true)")
        for table in ("procurement_cycles", "procurement_commands"):
            assert connection.execute("SELECT count(*) AS n FROM reconforge." + table + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    assert view["cycle"]["stage"] == "Draft"


def test_populated_downgrade_refuses_erasing_retained_sources(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_procurement_operations_schema import DOWNGRADE_SQL
    runtime = procurement_runtime
    create(runtime)
    with psycopg.connect(runtime.admin_dsn) as admin, pytest.raises(psycopg.errors.RaiseException, match="Retained procurement cycles prohibit downgrade"), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
