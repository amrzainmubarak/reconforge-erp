"""Real partial quantity reservations, FIFO, AP accrual and raw owner closure."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.procurement_partial import PartialQuantityPreparation, ProcurementPartialError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
)
from tests.test_postgres_inventory_receipt_posting import receipt_database as base_receipt_database
from tests.test_postgres_procurement_operations import procurement_phase_digest, request, seed_procurement

__all__ = ["pytestmark", "receipt_database"]
MAKER, CHECKER, POSTER = "partial-maker", "partial-checker", "partial-poster"


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    """The actual native fixture can also verify a direct schema-install milestone."""
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_procurement_partial_schema import install_postgres_procurement_partial
    delegated = base_receipt_database.__wrapped__()
    try:
        database = next(delegated)
        with psycopg.connect(database[0]) as admin:
            if admin.execute("SELECT to_regclass('reconforge.procurement_partial_orders')").fetchone()[0] is None:
                install_postgres_procurement_partial(admin)
            app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
            for table in ("procurement_partial_orders", "procurement_partial_receipts", "procurement_partial_invoices", "procurement_partial_commands"):
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))
        yield database
    finally:
        delegated.close()


def seed_procurement_partial(runtime: ReceiptRuntime) -> ReceiptRuntime:
    seed_procurement(runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for name in (MAKER, CHECKER, POSTER):
            identity.create_user(tenant_id=runtime.tenant, user_id="id-" + name, username=name, password=runtime.password, role_name="receipt-operator")
    return runtime


def create_procurement_partial_runtime(database: tuple[str, str], base_runtime: ReceiptRuntime | None = None) -> ReceiptRuntime:
    return seed_procurement_partial(base_runtime or create_receipt_runtime(database))


@pytest.fixture
def partial_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_procurement_partial_runtime(receipt_database)


def part(quantity: str, posting_date: str = "2026-10-03") -> PartialQuantityPreparation:
    return PartialQuantityPreparation(quantity=quantity, posting_date=posting_date, period_id="period", reason="Synthetic exact partial delivery")


def create_partial(runtime: ReceiptRuntime, number: str = "PARTIAL-1") -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        assert actor.user_id != actor.username
        view = PostgresProcurementPartialRepository(connection, runtime.tenant).create(replace(request(number), quantity="10"), command_id="partial-create-" + number, actor=actor)
    return action(runtime, action(runtime, view, "submit-order", MAKER), "approve-order", CHECKER)


def action(runtime: ReceiptRuntime, view: dict[str, Any], operation: str, actor_name: str,
           document_id: str | None = None) -> dict[str, Any]:
    with runtime.actor(actor_name) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        arguments = {"expected_version": view["order"]["row_version"], "command_id": "partial-action-" + str(view["order"]["row_version"]),
                     "reason": "Independent retained operational review", "document_id": document_id, "actor": actor}
        result = repository.act(view["order"]["id"], operation, **arguments)
        assert repository.act(view["order"]["id"], operation, **arguments) == result
        return result


def prepare_partial_receipt(runtime: ReceiptRuntime, view: dict[str, Any], quantity: str, posting_date: str = "2026-10-03") -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        args = {"expected_version": view["order"]["row_version"], "command_id": "partial-receipt-" + str(view["order"]["row_version"]), "actor": actor}
        result = repository.prepare_receipt(view["order"]["id"], part(quantity, posting_date), **args)
        assert repository.prepare_receipt(view["order"]["id"], part(quantity, posting_date), **args) == result
        return result


def receive_partial(runtime: ReceiptRuntime, view: dict[str, Any], quantity: str, posting_date: str = "2026-10-03") -> dict[str, Any]:
    view = prepare_partial_receipt(runtime, view, quantity, posting_date)
    identifier = view["receipts"][-1]["id"]
    return action(runtime, action(runtime, view, "review-receipt", CHECKER, identifier), "receive", POSTER, identifier)


def match_partial_invoice(runtime: ReceiptRuntime, view: dict[str, Any], quantity: str) -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        args = {"expected_version": view["order"]["row_version"], "command_id": "partial-invoice-" + str(view["order"]["row_version"]), "actor": actor}
        result = repository.match_invoice(view["order"]["id"], part(quantity), **args)
        assert repository.match_invoice(view["order"]["id"], part(quantity), **args) == result
        return result


def accrue_partial_invoice(runtime: ReceiptRuntime, view: dict[str, Any], quantity: str) -> dict[str, Any]:
    view = match_partial_invoice(runtime, view, quantity)
    identifier = view["invoices"][-1]["id"]
    for operation, actor in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER), ("post-accrual", POSTER)):
        view = action(runtime, view, operation, actor, identifier)
    return view


def complete_partial_accrual_cycle(runtime: ReceiptRuntime, number: str = "PARTIAL-1") -> dict[str, Any]:
    view = create_partial(runtime, number)
    view = accrue_partial_invoice(runtime, receive_partial(runtime, view, "4"), "3")
    return accrue_partial_invoice(runtime, receive_partial(runtime, view, "6", "2026-10-04"), "7")


def test_partial_four_and_six_receipts_three_and_seven_invoices_reconcile_fifo_ap_gl(partial_runtime: ReceiptRuntime) -> None:
    runtime = partial_runtime
    view = complete_partial_accrual_cycle(runtime)
    assert view["totals"] == {"ordered_quantity": "10", "reserved_receipt_quantity": "10", "received_quantity": "10", "invoiced_quantity": "10",
                              "received_minor": "12000", "accrued_minor": "12000", "paid_minor": "0", "outstanding_minor": "12000"}
    assert [item["total_minor"] for item in view["invoices"]] == ["3600", "8400"]
    with runtime.actor(POSTER) as (connection, _, actor):
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
        assert tuple(connection.execute("SELECT count(*),sum(original_quantity_scaled),sum(original_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (2, 10, 12000)
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 4
        assert tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (24000, 24000)


def test_prepared_receipts_reserve_exact_order_capacity(partial_runtime: ReceiptRuntime) -> None:
    view = prepare_partial_receipt(partial_runtime, create_partial(partial_runtime), "6")
    with pytest.raises(ProcurementPartialError, match="capacity"):
        prepare_partial_receipt(partial_runtime, view, "5")
    view = prepare_partial_receipt(partial_runtime, view, "4")
    assert view["totals"]["reserved_receipt_quantity"] == "10"
    assert view["totals"]["received_quantity"] == "0"


def test_backdated_second_receipt_is_refused_by_retained_fifo_engine(partial_runtime: ReceiptRuntime) -> None:
    from reconforge.domain.inventory_receipt_posting import InventoryReceiptPostingError

    runtime = partial_runtime
    view = receive_partial(runtime, create_partial(runtime), "4", "2026-10-04")
    view = prepare_partial_receipt(runtime, view, "6", "2026-10-03")
    identifier = view["receipts"][-1]["id"]
    view = action(runtime, view, "review-receipt", CHECKER, identifier)
    with runtime.actor(POSTER) as (connection, _, _):
        before = procurement_phase_digest(connection, runtime.tenant)
    with pytest.raises(InventoryReceiptPostingError, match="Backdated receipt"):
        action(runtime, view, "receive", POSTER, identifier)
    with runtime.actor(POSTER) as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view


def test_matched_invoices_reserve_posted_receipt_capacity_before_approval(partial_runtime: ReceiptRuntime) -> None:
    view = match_partial_invoice(partial_runtime, receive_partial(partial_runtime, create_partial(partial_runtime), "4"), "3")
    with pytest.raises(ProcurementPartialError, match="capacity"):
        match_partial_invoice(partial_runtime, view, "2")
    view = match_partial_invoice(partial_runtime, view, "1")
    assert view["totals"]["invoiced_quantity"] == "4"
    assert view["totals"]["accrued_minor"] == "0"


def test_concurrent_receipt_reservations_allow_one_current_version(partial_runtime: ReceiptRuntime) -> None:
    runtime = partial_runtime
    view = create_partial(runtime)
    def reserve(command: str) -> str:
        try:
            with runtime.actor(MAKER) as (connection, _, actor):
                PostgresProcurementPartialRepository(connection, runtime.tenant).prepare_receipt(view["order"]["id"], part("6"),
                    expected_version=view["order"]["row_version"], command_id=command, actor=actor)
            return "accepted"
        except ProcurementPartialError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["parallel-a", "parallel-b"]))
    assert sorted(results) == ["accepted", "procurement_partial_version_conflict"]


def test_stock_posting_rolls_back_when_native_ap_receipt_fails(partial_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = partial_runtime
    view = prepare_partial_receipt(runtime, create_partial(runtime), "4")
    identifier = view["receipts"][0]["id"]
    view = action(runtime, view, "review-receipt", CHECKER, identifier)
    with runtime.actor(POSTER) as (connection, _, actor):
        before = procurement_phase_digest(connection, runtime.tenant)
        repository = PostgresProcurementPartialRepository(connection, runtime.tenant)
        def fail(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("injected failure after FIFO and GL before native AP receipt")
        monkeypatch.setattr(repository.payables, "post_receipt", fail)
        with pytest.raises(RuntimeError, match="injected failure"):
            repository.act(view["order"]["id"], "receive", expected_version=view["order"]["row_version"], command_id="fault-after-gl", reason="Atomic recovery gate", actor=actor, document_id=identifier)
        assert procurement_phase_digest(connection, runtime.tenant) == before
    assert action(runtime, view, "receive", POSTER, identifier)["totals"]["received_quantity"] == "4"


@pytest.mark.parametrize("phase", ["receipt-review", "receipt-post", "invoice-approval", "accrual-review", "accrual-post", "native-receipt"])
def test_generic_participant_cannot_leave_partial_owner_stale(partial_runtime: ReceiptRuntime, phase: str) -> None:
    import psycopg
    runtime = partial_runtime
    view = create_partial(runtime)
    if phase.startswith("receipt"):
        view = prepare_partial_receipt(runtime, view, "4")
        if phase == "receipt-post":
            view = action(runtime, view, "review-receipt", CHECKER, view["receipts"][0]["id"])
    elif phase != "native-receipt":
        view = match_partial_invoice(runtime, receive_partial(runtime, view, "4"), "3")
        if phase.startswith("accrual"):
            identifier = view["invoices"][0]["id"]
            view = action(runtime, action(runtime, view, "approve-invoice", CHECKER, identifier), "prepare-accrual", MAKER, identifier)
            if phase == "accrual-post":
                view = action(runtime, view, "review-accrual", CHECKER, identifier)
    actor_name = POSTER if phase.endswith("post") else CHECKER if phase.endswith(("review", "approval")) else MAKER
    with runtime.actor(actor_name) as (connection, _, _):
        before = procurement_phase_digest(connection, runtime.tenant)
    with pytest.raises(psycopg.errors.CheckViolation, match="Partial|partial"), runtime.actor(actor_name) as (connection, receipts, actor):
        payables = PostgresPayablesRepository(connection, runtime.tenant)
        if phase == "receipt-review":
            plan = receipts.get_plan(view["receipts"][0]["receipt_plan_id"], actor=actor)["plan"]
            receipts.review(plan["plan_id"], expected_plan_digest=plan["plan_digest"], command_id="detached-review", reason="Real generic review", actor=actor)
        elif phase == "receipt-post":
            plan = receipts.get_plan(view["receipts"][0]["receipt_plan_id"], actor=actor)
            receipts.commit(plan["plan"]["plan_id"], expected_review_digest=plan["review"]["review_digest"], command_id="detached-post", reason="Real generic posting", actor=actor)
        elif phase == "invoice-approval":
            invoice = payables.get_supplier_invoice(view["invoices"][0]["native_invoice_id"])
            payables.approve_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.user_id)
        elif phase.startswith("accrual"):
            finance = PostgresOperationalFinanceRepository(connection, runtime.tenant)
            plan = finance.get(view["invoices"][0]["accrual_plan_id"], actor=actor)
            method = finance.review if phase == "accrual-review" else finance.post
            method(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="detached-finance", reason="Real generic financial phase", actor=actor)
        else:
            order = payables.get_purchase_order(view["order"]["purchase_order_id"])
            payables.post_receipt(receipt_number="EXTERNAL-RECEIPT", purchase_order_id=order["id"], receipt_date="2026-10-03",
                quantities={order["lines"][0]["id"]: "4"}, workspace="work", actor_label=actor.user_id)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor(actor_name) as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view


def test_retained_partial_history_and_downgrade_are_refused(partial_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_procurement_partial_schema import DOWNGRADE_SQL
    runtime = partial_runtime
    view = complete_partial_accrual_cycle(runtime)
    for sql in ("DELETE FROM reconforge.procurement_partial_orders WHERE tenant_id=%s", "UPDATE reconforge.procurement_partial_receipts SET quantity=quantity+1 WHERE tenant_id=%s",
                "UPDATE reconforge.procurement_partial_orders SET row_version=row_version+1 WHERE tenant_id=%s"):
        with pytest.raises(psycopg.errors.CheckViolation, match="Partial|partial"), runtime.actor(POSTER) as (connection, _, _):
            connection.execute(sql, (runtime.tenant,))
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with psycopg.connect(runtime.admin_dsn) as admin, pytest.raises(psycopg.errors.RaiseException, match="Retained partial"):
        admin.execute(DOWNGRADE_SQL)
    with runtime.actor(POSTER) as (connection, _, actor):
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view


def test_generic_manual_payment_cannot_bypass_reviewed_installment_owner(partial_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.domain.payables_payment_link import payment_external_reference
    from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
    from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
    from reconforge.infrastructure.postgres_payables_payment_link import PostgresPayablesPaymentLinkRepository

    runtime = partial_runtime
    view = accrue_partial_invoice(runtime, receive_partial(runtime, create_partial(runtime), "4"), "3")
    invoice_id = view["invoices"][0]["native_invoice_id"]
    with runtime.actor(MAKER) as (connection, _, actor):
        entry = PostgresFinanceCoreRepository(connection, runtime.tenant).create_entry(entry_number="UNOWNED-MANUAL-AP-PAYMENT",
            organization_code="ORG", entity_code="ENTITY", period_id="period", journal_code="STOCK", posting_date="2026-10-04",
            description="Real unrelated manual financial source", workspace="work", external_reference=payment_external_reference(invoice_id),
            actor_label=actor.user_id, lines=[{"account_code": "AP", "debit": "15.00", "credit": "0"},
                                           {"account_code": "CASH", "debit": "0", "credit": "15.00"}])
    with runtime.actor(CHECKER) as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, runtime.tenant).validate_entry(entry["id"], reason="Actual independent financial review", actor_label=actor.user_id)
    with runtime.actor(POSTER) as (connection, _, actor):
        posting = PostgresFinancePostingRepository(connection, runtime.tenant)
        preview = posting.preview(entry["id"], actor=actor)
        effect = posting.post(entry["id"], command_id="unowned-manual-post", expected_validation_digest=preview["current_content_digest"],
                              reason="Actual independent manual financial posting", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation, match="installment|Installment"), runtime.actor(POSTER) as (connection, _, actor):
        accounts = {row["account_code"]: row["id"] for row in connection.execute(
            "SELECT account_code,id FROM reconforge.finance_accounts WHERE tenant_id=%s AND account_code IN ('AP','CASH')", (runtime.tenant,)).fetchall()}
        PostgresPayablesPaymentLinkRepository(connection, runtime.tenant).link_finance_payment(invoice_id,
            finance_effect_id=effect["id"], ap_account_id=accounts["AP"], cash_account_id=accounts["CASH"],
            expected_invoice_version=view["invoices"][0]["native_version"], command_id="detached-native-ap-payment", actor_label=actor.user_id)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor(POSTER) as (connection, _, actor):
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
