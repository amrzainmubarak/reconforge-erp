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


def reviewed_partial_publication(runtime: ReceiptRuntime, phase: str) -> tuple[dict[str, Any], str, str]:
    view = create_partial(runtime)
    if phase == "receipt":
        view = prepare_partial_receipt(runtime, view, "4")
        identifier = view["receipts"][0]["id"]
        return action(runtime, view, "review-receipt", CHECKER, identifier), "receive", identifier
    view = match_partial_invoice(runtime, receive_partial(runtime, view, "4"), "3")
    identifier = view["invoices"][0]["id"]
    for operation, actor in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER)):
        view = action(runtime, view, operation, actor, identifier)
    return view, "post-accrual", identifier


def partial_publication_digest(connection: Any, tenant: str, *, include_audit: bool = True) -> str:
    from psycopg import sql

    from reconforge.domain.finance_posting import digest_payload

    captured: dict[str, Any] = {"native": procurement_phase_digest(connection, tenant, include_audit=include_audit)}
    for table in ("procurement_partial_orders", "procurement_partial_receipts", "procurement_partial_invoices", "procurement_partial_commands"):
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) AS payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text")
                                  .format(sql.Identifier(table)), (tenant,)).fetchall()
        captured[table] = [row["payload"] for row in rows]
    return digest_payload(captured)


@pytest.mark.parametrize("phase", ["receipt", "accrual"])
def test_partial_reviewer_cannot_publish_and_third_poster_can_continue(partial_runtime: ReceiptRuntime, phase: str) -> None:
    runtime = partial_runtime
    view, operation, identifier = reviewed_partial_publication(runtime, phase)
    with runtime.actor(CHECKER) as (connection, _, _):
        before = partial_publication_digest(connection, runtime.tenant)
    with pytest.raises(ProcurementPartialError, match="three distinct"):
        action(runtime, view, operation, CHECKER, identifier)
    with runtime.actor(CHECKER) as (connection, _, actor):
        assert partial_publication_digest(connection, runtime.tenant) == before
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
    posted = action(runtime, view, operation, POSTER, identifier)
    assert posted["order"]["row_version"] == view["order"]["row_version"] + 1
    assert posted["receipts" if phase == "receipt" else "invoices"][0]["stage"] == ("Posted" if phase == "receipt" else "Accrued")
    part = posted["receipts" if phase == "receipt" else "invoices"][0]
    prefix = "" if phase == "receipt" else "accrual_"
    assert [part[prefix + name + "_actor_id"] for name in ("preparer", "reviewer", "posted")] == ["id-" + name for name in (MAKER, CHECKER, POSTER)]


@pytest.mark.parametrize("phase", ["receipt", "accrual"])
def test_partial_raw_publication_closure_rejects_reviewer_and_rolls_back_real_effects(
    partial_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    import psycopg

    runtime = partial_runtime
    view, operation, identifier = reviewed_partial_publication(runtime, phase)
    with runtime.actor(CHECKER) as (connection, _, _):
        before = partial_publication_digest(connection, runtime.tenant)
        effect_count = connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0]
    # Bypass ONLY the owner Python check to exercise the legacy two-human native
    # engine and real source writes. The deferred database policy stays enabled.
    with monkeypatch.context() as patch:
        patch.setattr("reconforge.infrastructure.postgres_procurement_partial.require_third_poster", lambda *_: None)
        with pytest.raises(psycopg.errors.CheckViolation, match="three distinct") as refused, runtime.actor(CHECKER) as (connection, _, actor):
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
            result = PostgresProcurementPartialRepository(connection, runtime.tenant).act(view["order"]["id"], operation,
                expected_version=view["order"]["row_version"], command_id="raw-reviewer-publication", reason="Exercise source-owner SQL closure",
                document_id=identifier, actor=actor)
            assert result["order"]["row_version"] == view["order"]["row_version"] + 1
            assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == effect_count + 1
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert refused.value.diag.constraint_name == "procurement_partial_owner_phase"
    with runtime.actor(CHECKER) as (connection, _, actor):
        assert partial_publication_digest(connection, runtime.tenant) == before
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
    assert action(runtime, view, operation, POSTER, identifier)["order"]["row_version"] == view["order"]["row_version"] + 1


@pytest.mark.parametrize("phase", ["receipt", "accrual"])
def test_unowned_native_participant_preserves_legacy_reviewer_posting_policy(receipt_database: tuple[str, str], phase: str) -> None:
    if phase == "receipt":
        from tests.test_postgres_inventory_receipt_posting import prepare_and_review

        runtime = create_receipt_runtime(receipt_database)
        plan, review = prepare_and_review(runtime)
        with runtime.actor("checker") as (connection, receipts, actor):
            effect = receipts.commit(plan["plan_id"], command_id="legacy-checker-post", expected_review_digest=review["review_digest"],
                                     reason="Unowned receipt retains its native policy", actor=actor)
            assert effect["posted_actor_id"] == actor.user_id == review["reviewer"]["user_id"]
            assert connection.execute("SELECT count(*) FROM reconforge.procurement_partial_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0
    else:
        from tests.test_postgres_operational_finance import prepare_review
        from tests.test_postgres_operational_finance import runtime as native_runtime

        source = native_runtime.__wrapped__(receipt_database)
        runtime = source[0]
        plan = prepare_review(source)
        with runtime.actor("checker") as (connection, _, actor):
            posted = PostgresOperationalFinanceRepository(connection, runtime.tenant).post(plan["id"], expected_plan_digest=plan["plan_digest"],
                command_id="legacy-checker-post", reason="Unowned operational accrual retains its native policy", actor=actor)
            assert posted["status"] == "Posted" and plan["reviewer_actor_id"] == actor.user_id
            assert connection.execute("SELECT posted_actor_id FROM reconforge.operational_finance_links WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, plan["id"])).fetchone()[0] == actor.user_id
            assert connection.execute("SELECT count(*) FROM reconforge.procurement_partial_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0


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


def test_partial_order_rejects_fraction_beyond_stock_unit_scale(partial_runtime: ReceiptRuntime) -> None:
    from reconforge.platform.common import PlatformError

    runtime = partial_runtime
    with pytest.raises(PlatformError, match="precision"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresProcurementPartialRepository(connection, runtime.tenant).create(replace(request(), quantity="10.5"),
            command_id="invalid-order-item-scale", actor=actor)


def test_partial_invoice_rejects_fraction_beyond_retained_receipt_unit_scale(partial_runtime: ReceiptRuntime) -> None:
    from reconforge.platform.common import PlatformError

    runtime = partial_runtime
    view = receive_partial(runtime, create_partial(runtime), "4")
    with pytest.raises(PlatformError, match="precision"):
        match_partial_invoice(runtime, view, "3.5")
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view


def test_second_raw_receipt_cannot_reuse_first_owner_command_version(partial_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.domain.inventory_receipt_posting import ReceiptPreparation

    runtime = partial_runtime
    view = prepare_partial_receipt(runtime, create_partial(runtime), "4")
    existing = view["receipts"][0]
    with pytest.raises(psycopg.errors.CheckViolation, match="command|version"), runtime.actor(MAKER) as (connection, receipts, actor):
        plan = receipts.prepare_receipt(ReceiptPreparation(receipt_number="PPR-" + view["order"]["number"] + "-2",
            posting_date="2026-10-03", period_id="period", item_code="ITEM", location_code="MAIN/STOCK", quantity="4",
            total_value_minor=4800, policy_code="FIFO", workspace="work", organization_code="ORG", entity_code="ENTITY",
            reason="Actual detached source reusing another owner acknowledgement"), command_id="raw-second-receipt", actor=actor)
        connection.execute("""INSERT INTO reconforge.procurement_partial_receipts(tenant_id,id,order_id,sequence,number,
            quantity,quantity_text,total_minor,posting_date,period_id,receipt_plan_id,created_version)
            VALUES(%s,'RAW-CLONED-RECEIPT',%s,2,%s,4,'4',4800,'2026-10-03','period',%s,%s)""",
            (runtime.tenant, view["order"]["id"], plan["source"]["number"], plan["plan_id"], existing["created_version"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view


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


def test_all_partial_tables_deny_cross_hierarchy_sql_reads_and_writes(partial_runtime: ReceiptRuntime) -> None:
    import json

    import psycopg
    from psycopg import sql

    runtime = partial_runtime
    view = accrue_partial_invoice(runtime, receive_partial(runtime, create_partial(runtime), "4"), "3")
    tables = ("procurement_partial_orders", "procurement_partial_receipts",
              "procurement_partial_invoices", "procurement_partial_commands")
    rows: dict[str, dict[str, Any]] = {}
    with runtime.actor(POSTER) as (connection, _, _):
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        for table in tables:
            assert connection.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
                                      ("reconforge." + table,)).fetchone()["relforcerowsecurity"]
            row = connection.execute(sql.SQL("SELECT * FROM reconforge.{} WHERE tenant_id=%s LIMIT 1").format(sql.Identifier(table)),
                                     (runtime.tenant,)).fetchone()
            assert row is not None
            rows[table] = dict(row)
    for setting in ("app.tenant_id", "app.workspace_id", "app.organization_id", "app.legal_entity_id", "app.entity_id"):
        with runtime.actor(POSTER) as (connection, _, _):
            connection.execute("SELECT set_config(%s,%s,true)", (setting, "outside-partial-authority"))
            for table in tables:
                query = sql.SQL("SELECT count(*) AS count FROM reconforge.{} WHERE tenant_id=%s").format(sql.Identifier(table))
                assert connection.execute(query, (runtime.tenant,)).fetchone()["count"] == 0
                update = sql.SQL("UPDATE reconforge.{} SET tenant_id=tenant_id WHERE tenant_id=%s RETURNING tenant_id").format(sql.Identifier(table))
                assert connection.execute(update, (runtime.tenant,)).fetchall() == []
                insert = sql.SQL("INSERT INTO reconforge.{} SELECT candidate.* FROM jsonb_populate_record(NULL::reconforge.{},%s::jsonb) candidate").format(
                    sql.Identifier(table), sql.Identifier(table))
                with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                    connection.execute(insert, (json.dumps(rows[table], default=str),))
    with runtime.actor(POSTER) as (connection, _, actor):
        assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor) == view
