"""Actual multi-unit, multi-warehouse partial purchase-to-pay under restricted RLS."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from reconforge.domain.finance_posting import digest_payload
from reconforge.domain.procurement_partial import (
    MultilineInvoicePreparation,
    PartialQuantityPreparation,
    ProcurementLineQuantity,
    ProcurementPartialError,
)
from reconforge.infrastructure.postgres_financial_installments import PostgresFinancialInstallmentsRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from tests.test_postgres_financial_installments import post, preparation, review
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_partial import (
    CHECKER,
    MAKER,
    POSTER,
    create_procurement_partial_runtime,
    partial_publication_digest,
    pytestmark,
)
from tests.test_postgres_procurement_partial import receipt_database as base_receipt_database
from tests.test_procurement_multiline import enterprise_request

__all__ = ["pytestmark", "receipt_database"]


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_procurement_partial_multiline_schema import (
        install_postgres_procurement_partial_multiline,
    )
    delegated = base_receipt_database.__wrapped__()
    try:
        database = next(delegated)
        with psycopg.connect(database[0]) as admin:
            install_postgres_procurement_partial_multiline(admin)
            app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
            for table in ("procurement_partial_order_lines", "procurement_partial_invoice_lines"):
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))
        yield database
    finally:
        delegated.close()


def create_multiline_runtime(database: tuple[str, str]) -> ReceiptRuntime:
    runtime = create_procurement_partial_runtime(database)
    with runtime.actor(MAKER) as (connection, _, _):
        inventory = PostgresInventoryCoreRepository(connection, runtime.tenant)
        inventory.upsert_uom(uom_code="KG", name="Kilograms", decimal_places=2, category="Weight", workspace="work")
        inventory.upsert_item(item_code="WEIGHT", name="Synthetic weighted product", organization_code="ORG", uom_code="KG",
            inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_warehouse(warehouse_code="NORTH", name="Synthetic north warehouse", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="NORTH", location_code="STOCK", name="Synthetic north receiving", organization_code="ORG", workspace="work")
    return runtime


@pytest.fixture
def multiline_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_multiline_runtime(receipt_database)


def create_order(runtime: ReceiptRuntime, number: str = "MULTI-1") -> dict[str, Any]:
    request = enterprise_request(number)
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        view = repository.create_multiline(request, command_id="create-" + number, actor=actor)
        assert repository.create_multiline(request, command_id="create-" + number, actor=actor) == view
    return action(runtime, action(runtime, view, "submit-order", MAKER), "approve-order", CHECKER)


def action(runtime: ReceiptRuntime, view: dict[str, Any], operation: str, actor_name: str,
           document_id: str | None = None) -> dict[str, Any]:
    with runtime.actor(actor_name) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        arguments = {"expected_version": view["order"]["row_version"],
            "command_id": view["order"]["number"] + "-phase-" + str(view["order"]["row_version"]),
            "reason": "Independent retained operational review", "document_id": document_id, "actor": actor}
        result = repository.act(view["order"]["id"], operation, **arguments)
        assert repository.act(view["order"]["id"], operation, **arguments) == result
        return result


def prepare_line(runtime: ReceiptRuntime, view: dict[str, Any], line: int, quantity: str, date: str = "2026-10-03",
                 command: str | None = None) -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        arguments = {"expected_version": view["order"]["row_version"], "command_id": command or view["order"]["number"] + "-receive-" + str(view["order"]["row_version"]), "actor": actor}
        request = PartialQuantityPreparation(quantity=quantity, posting_date=date, period_id="period", reason="Independent multiwarehouse shipment")
        result = repository.prepare_receipt_line(view["order"]["id"], view["lines"][line]["id"], request, **arguments)
        assert repository.prepare_receipt_line(view["order"]["id"], view["lines"][line]["id"], request, **arguments) == result
        return result


def receive_line(runtime: ReceiptRuntime, view: dict[str, Any], line: int, quantity: str, date: str = "2026-10-03") -> dict[str, Any]:
    view = prepare_line(runtime, view, line, quantity, date)
    identifier = view["receipts"][-1]["id"]
    return action(runtime, action(runtime, view, "review-receipt", CHECKER, identifier), "receive", POSTER, identifier)


def invoice_lines(runtime: ReceiptRuntime, view: dict[str, Any], quantities: tuple[tuple[int, str], ...],
                  date: str = "2026-10-03") -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        request = MultilineInvoicePreparation(lines=tuple(ProcurementLineQuantity(line_id=view["lines"][index]["id"], quantity=quantity) for index, quantity in quantities),
            posting_date=date, period_id="period", reason="Exact per-line three-way invoice matching")
        arguments = {"expected_version": view["order"]["row_version"], "command_id": view["order"]["number"] + "-invoice-" + str(view["order"]["row_version"]), "actor": actor}
        result = repository.match_invoice_lines(view["order"]["id"], request, **arguments)
        assert repository.match_invoice_lines(view["order"]["id"], request, **arguments) == result
        return result


def accrue_invoice(runtime: ReceiptRuntime, view: dict[str, Any], quantities: tuple[tuple[int, str], ...], date: str = "2026-10-03") -> dict[str, Any]:
    view = invoice_lines(runtime, view, quantities, date)
    identifier = view["invoices"][-1]["id"]
    for operation, username in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER), ("post-accrual", POSTER)):
        view = action(runtime, view, operation, username, identifier)
    return view


def pay_invoice(runtime: ReceiptRuntime, invoice_id: str, amount: int, command: str, date: str = "2026-10-03") -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresFinancialInstallmentsRepository(connection, runtime.tenant)
        request = replace(preparation(invoice_id, amount), posting_date=date)
        plan = repository.prepare(request, command_id="prepare-" + command, actor=actor)
        assert repository.prepare(request, command_id="prepare-" + command, actor=actor) == plan
    return post(runtime, review(runtime, plan, command), command)


def enterprise_digest(connection: Any, tenant: str) -> str:
    from psycopg import sql
    captured = {"native": partial_publication_digest(connection, tenant)}
    for table in ("procurement_partial_order_lines", "procurement_partial_invoice_lines"):
        captured[table] = [row["payload"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) AS payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text")
            .format(sql.Identifier(table)), (tenant,)).fetchall()]
    return digest_payload(captured)


def test_two_products_two_warehouses_two_native_multiline_invoices_four_payments(multiline_runtime: ReceiptRuntime) -> None:
    runtime = multiline_runtime
    view = create_order(runtime)
    assert view["order"]["line_count"] == 2 and view["order"]["total_minor"] == "17000"
    view = receive_line(runtime, receive_line(runtime, view, 0, "4"), 1, "1.25")
    view = accrue_invoice(runtime, view, ((0, "3"), (1, "1")))
    first = view["invoices"][0]
    assert first["quantity_text"] is None and first["total_minor"] == "5600" and len(first["lines"]) == 2
    for amount, command in ((2000, "first-a"), (3600, "first-b")):
        pay_invoice(runtime, first["native_invoice_id"], amount, command)
    view = receive_line(runtime, receive_line(runtime, view, 0, "6", "2026-10-04"), 1, "1.25", "2026-10-04")
    view = accrue_invoice(runtime, view, ((0, "7"), (1, "1.50")), "2026-10-04")
    second = view["invoices"][-1]
    for amount, command in ((4000, "second-a"), (7400, "second-b")):
        pay_invoice(runtime, second["native_invoice_id"], amount, command, "2026-10-04")
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        view = repository.get(view["order"]["id"], actor=actor)
        assert [(line["uom_code"], Decimal(line["received_quantity"]), Decimal(line["invoiced_quantity"])) for line in view["lines"]] == [("EA", Decimal("10"), Decimal("10")), ("KG", Decimal("2.50"), Decimal("2.50"))]
        for invoice in view["invoices"]:
            history = repository.payment_page(view["order"]["id"], invoice["id"], actor=actor)
            assert history["next_after"] is None and len(history["records"]) == 2
            assert all(plan["phase"] == 2 and plan["posting_effect_id"] and plan["payment_link_id"] for plan in history["records"])
            assert sum(int(plan["amount_minor"]) for plan in history["records"]) == int(invoice["total_minor"])
        assert view["totals"] == {"ordered_quantity": "0", "reserved_receipt_quantity": "0", "received_quantity": "0", "invoiced_quantity": "0",
            "received_minor": "17000", "accrued_minor": "17000", "paid_minor": "17000", "outstanding_minor": "0"}
        assert [invoice["native_status"] for invoice in view["invoices"]] == ["Paid", "Paid"]
        assert connection.execute("SELECT count(*) FROM reconforge.ap_purchase_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 10
        assert tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (51000, 51000)
        layers = connection.execute("""SELECT i.item_code,sum(c.remaining_quantity_scaled) AS quantity,sum(c.remaining_value_minor) AS value
            FROM reconforge.inventory_cost_layers c JOIN reconforge.inventory_items i ON i.tenant_id=c.tenant_id AND i.id=c.item_id
            WHERE c.tenant_id=%s GROUP BY i.item_code ORDER BY i.item_code""", (runtime.tenant,)).fetchall()
        assert [dict(item) for item in layers] == [{"item_code": "ITEM", "quantity": 10, "value": 12000}, {"item_code": "WEIGHT", "quantity": 250, "value": 5000}]


def test_line_capacity_and_atomic_multi_invoice_admission(multiline_runtime: ReceiptRuntime) -> None:
    runtime = multiline_runtime
    view = receive_line(runtime, create_order(runtime), 0, "4")
    with runtime.actor(MAKER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    with pytest.raises(ProcurementPartialError, match="capacity"):
        invoice_lines(runtime, view, ((0, "3"), (1, "0.50")))
    with pytest.raises(ProcurementPartialError, match="capacity"):
        prepare_line(runtime, view, 0, "7")
    with runtime.actor(MAKER) as (connection, _, _):
        assert enterprise_digest(connection, runtime.tenant) == before
    view = invoice_lines(runtime, view, ((0, "3"),))
    with pytest.raises(ProcurementPartialError, match="capacity"):
        invoice_lines(runtime, view, ((0, "2"),))


def test_concurrent_same_command_replays_one_line_reservation(multiline_runtime: ReceiptRuntime) -> None:
    runtime = multiline_runtime
    view = create_order(runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: prepare_line(runtime, view, 0, "7", command="same-live-command"), range(2)))
    assert results[0] == results[1]
    with runtime.actor(MAKER) as (connection, _, actor):
        fresh = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
        assert fresh["lines"][0]["reserved_receipt_quantity"] == "7" and len(fresh["receipts"]) == 1


def test_concurrent_distinct_commands_fence_parent_and_capacity(multiline_runtime: ReceiptRuntime) -> None:
    runtime = multiline_runtime
    view = create_order(runtime)
    def attempt(index: int) -> str:
        try:
            prepare_line(runtime, view, 0, "7", command="racing-" + str(index))
            return "prepared"
        except ProcurementPartialError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sorted(outcomes) == ["prepared", "procurement_partial_version_conflict"]
    with runtime.actor(MAKER) as (connection, _, actor):
        fresh = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
    with pytest.raises(ProcurementPartialError, match="capacity"):
        prepare_line(runtime, fresh, 0, "7", command="retry-new-version")


def test_late_ack_failure_rolls_back_native_fifo_ap_gl_and_exact_retry(multiline_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = multiline_runtime
    view = prepare_line(runtime, create_order(runtime), 1, "1.25")
    identifier = view["receipts"][-1]["id"]
    view = action(runtime, view, "review-receipt", CHECKER, identifier)
    with runtime.actor(POSTER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    original = PostgresProcurementPartialRepository._remember
    def fail_after_real_ack(self: PostgresProcurementPartialRepository, *arguments: Any, **keywords: Any) -> dict[str, Any]:
        original(self, *arguments, **keywords)
        raise RuntimeError("Injected failure after real owner acknowledgement")
    with monkeypatch.context() as patched:
        patched.setattr(PostgresProcurementPartialRepository, "_remember", fail_after_real_ack)
        with pytest.raises(RuntimeError, match="real owner acknowledgement"):
            action(runtime, view, "receive", POSTER, identifier)
    with runtime.actor(POSTER) as (connection, _, _):
        assert enterprise_digest(connection, runtime.tenant) == before
    published = action(runtime, view, "receive", POSTER, identifier)
    assert published["receipts"][-1]["stage"] == "Posted"


@pytest.mark.parametrize("phase", ["receipt", "accrual"])
def test_multiline_raw_owner_closure_rejects_reviewer_publication(multiline_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch, phase: str) -> None:
    import psycopg

    import reconforge.infrastructure.postgres_procurement_partial as module
    runtime = multiline_runtime
    view = prepare_line(runtime, create_order(runtime), 0, "4")
    identifier = view["receipts"][-1]["id"]
    view = action(runtime, view, "review-receipt", CHECKER, identifier)
    operation = "receive"
    if phase == "accrual":
        view = invoice_lines(runtime, action(runtime, view, "receive", POSTER, identifier), ((0, "3"),))
        identifier = view["invoices"][-1]["id"]
        for action_name, username in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER)):
            view = action(runtime, view, action_name, username, identifier)
        operation = "post-accrual"
    with runtime.actor(CHECKER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    monkeypatch.setattr(module, "require_third_poster", lambda *_: None)
    with pytest.raises(psycopg.errors.CheckViolation, match="three distinct"):
        action(runtime, view, operation, CHECKER, identifier)
    with runtime.actor(CHECKER) as (connection, _, _):
        assert enterprise_digest(connection, runtime.tenant) == before


def test_new_lines_are_immutable_and_parent_keyset_has_no_duplicate_pages(multiline_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = multiline_runtime
    created = [create_order(runtime, "PAGE-" + str(index)) for index in range(3)]
    created = [prepare_line(runtime, view, 0, "4") for view in created]
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        before = enterprise_digest(connection, runtime.tenant)
        first = repository.order_page("work", actor=actor, page_size=2)
        second = repository.order_page("work", actor=actor, after=first["next_after"], page_size=2)
        assert len(first["records"]) == 2 and len(second["records"]) == 1 and second["next_after"] is None
        assert {item["id"] for item in first["records"] + second["records"]} == {view["order"]["id"] for view in created}
        assert connection.execute("SELECT count(*) FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 3
        assert all(view["lines"][0]["reserved_receipt_quantity"] == "4" for view in created)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("UPDATE reconforge.procurement_partial_order_lines SET quantity=quantity+1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, created[0]["lines"][0]["id"]))
        assert enterprise_digest(connection, runtime.tenant) == before


def test_initial_typed_location_mismatch_is_rejected_after_actual_source_writes(multiline_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    runtime = multiline_runtime
    with runtime.actor(MAKER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    original = PostgresInventoryCoreRepository._location_reference
    def corrupt_typed_location(self: PostgresInventoryCoreRepository, workspace: str, organization: str, entity: str, value: object) -> dict[str, Any] | None:
        return original(self, workspace, organization, entity, "MAIN/STOCK" if value == "NORTH/STOCK" else value)
    monkeypatch.setattr(PostgresInventoryCoreRepository, "_location_reference", corrupt_typed_location)
    with pytest.raises(psycopg.errors.CheckViolation, match="retained item, unit, price or native source"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresProcurementPartialRepository(connection, runtime.tenant).create_multiline(enterprise_request("BAD-LOCATION"), command_id="bad-typed-location", actor=actor)
    with runtime.actor(MAKER) as (connection, _, _):
        assert enterprise_digest(connection, runtime.tenant) == before


def test_128_retained_native_purchase_lines_remain_distinct_and_tenant_isolated(receipt_database: tuple[str, str]) -> None:
    from reconforge.domain.procurement_partial import ProcurementOrderLine
    runtime = create_multiline_runtime(receipt_database)
    request = replace(enterprise_request("BOUND-128"), lines=tuple(ProcurementOrderLine(
        item_code="ITEM", quantity="1", unit_price_minor=1200, location_code="MAIN/STOCK", policy_code="FIFO") for _ in range(128)))
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        view = repository.create_multiline(request, command_id="bounded128-native", actor=actor)
        assert len(view["lines"]) == 128 and len({line["id"] for line in view["lines"]}) == 128
        assert view["order"]["total_minor"] == "153600"
        assert view["pages"]["page_size"] == 4
        assert connection.execute("SELECT count(*) FROM reconforge.ap_purchase_order_lines WHERE tenant_id=%s AND purchase_order_id=%s",
            (runtime.tenant, view["order"]["purchase_order_id"])).fetchone()[0] == 128
    foreign = create_multiline_runtime(receipt_database)
    with foreign.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, foreign.tenant)
        assert repository.order_page("work", actor=actor)["records"] == []
        assert connection.execute("SELECT count(*) FROM reconforge.procurement_partial_order_lines").fetchone()[0] == 0
        with pytest.raises(ProcurementPartialError, match="absent or outside"):
            repository.get(view["order"]["id"], actor=actor)
