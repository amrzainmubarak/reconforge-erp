"""Independent original-cost oracles and raw SQL native supplier-debit closure."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.supplier_returns import SupplierReturnPreparation
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.infrastructure.postgres_supplier_returns import PostgresSupplierReturnsRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_multiline import (
    accrue_invoice,
    create_multiline_runtime,
    create_order,
    enterprise_digest,
    pay_invoice,
    receive_line,
)
from tests.test_postgres_procurement_multiline import receipt_database as base_receipt_database
from tests.test_postgres_procurement_partial import CHECKER, MAKER, POSTER, pytestmark

__all__ = ["pytestmark", "receipt_database"]


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    delegated = base_receipt_database.__wrapped__()
    try:
        yield next(delegated)
    finally:
        delegated.close()


@pytest.fixture
def runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    selected = create_multiline_runtime(receipt_database)
    with selected.actor(MAKER) as (connection, _, _):
        identities = PostgresIdentityRepository(connection)
        scopes = PostgresScopeAuthorityRepository(connection)
        for name in (MAKER, CHECKER, POSTER):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                scopes.grant(tenant_id=selected.tenant, grant_id="sr-grant-" + name + kind, principal_type="user", principal_id="id-" + name,
                             scope_type=kind, scope_id=identifier, actor_id="id-" + name)
        for permission in ("inventory.valuation.reverse.manage", "inventory.valuation.reverse.approve", "finance_core.reverse"):
            identities.create_permission(tenant_id=selected.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=selected.tenant, role_name="receipt-operator", permission_name=permission)
    return selected


def source(runtime: ReceiptRuntime) -> dict[str, Any]:
    purchase = receive_line(runtime, create_order(runtime), 0, "2")
    return accrue_invoice(runtime, purchase, ((0, "2"),))


def preparation(purchase: dict[str, Any], number: str = "SR1-RETURN-1") -> SupplierReturnPreparation:
    line_id = purchase["invoices"][0]["lines"][0]["line_id"]
    receipt = next(row for row in purchase["receipts"] if row["order_line_id"] == line_id)
    return SupplierReturnPreparation(order_id=purchase["order"]["id"], receipt_id=receipt["id"],
        invoice_id=purchase["invoices"][0]["id"], number=number, period_id="period", posting_date="2026-10-05",
        expense_account_code="ADJUSTMENT", reason="Return complete original unused supplier receipt")


def prepare(runtime: ReceiptRuntime, purchase: dict[str, Any]) -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repo = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        plan = repo.prepare(preparation(purchase), command_id="sr-prepare", actor=actor)
        assert repo.prepare(preparation(purchase), command_id="sr-prepare", actor=actor) == plan
        return plan


def phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, actor_name: str) -> dict[str, Any]:
    with runtime.actor(actor_name) as (connection, _, actor):
        repo = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        args = dict(expected_plan_digest=plan["plan_digest"], command_id="sr-" + operation, reason="Independent original supplier debit " + operation, actor=actor)
        result = getattr(repo, operation)(plan["id"], **args)
        assert getattr(repo, operation)(plan["id"], **args) == result
        return result


def snapshot(runtime: ReceiptRuntime) -> str:
    from psycopg import sql
    with runtime.actor(MAKER) as (connection, _, _):
        result = {"native": enterprise_digest(connection, runtime.tenant)}
        for table in ("supplier_return_plans", "supplier_return_events", "supplier_return_commands", "ap_supplier_invoice_credits"):
            result[table] = [row["value"] for row in connection.execute(sql.SQL("SELECT to_jsonb(x) AS value FROM reconforge.{} x WHERE tenant_id=%s ORDER BY to_jsonb(x)::text")
                .format(sql.Identifier(table)), (runtime.tenant,)).fetchall()]
        return digest_payload(result)


def test_full_native_unused_receipt_and_original_unpaid_ap_are_removed_atomically(runtime: ReceiptRuntime) -> None:
    purchase = source(runtime)
    plan = phase(runtime, phase(runtime, prepare(runtime, purchase), "review", CHECKER), "post", POSTER)
    assert (plan["credit_minor"], plan["inventory_removed_minor"], plan["charge_expense_minor"], plan["amount_minor"]) == ("2400", "2400", "0", "4800")
    assert len(plan["posting_effect_ids"]) == 2
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresSupplierReturnsRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == plan
        layer = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s",
                                   (runtime.tenant, plan["inverse_plan"]["artifacts"]["cost_layer_id"])).fetchone()
        assert (layer["remaining_quantity_scaled"], layer["remaining_value_minor"]) == (0, 0)
        invoice = connection.execute("SELECT status,total_minor FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["native_invoice_id"])).fetchone()
        assert (invoice["status"], invoice["total_minor"]) == ("Credited", 2400)
        totals = connection.execute("""SELECT sum((line->>'debit_minor')::numeric) AS debit,
            sum((line->>'credit_minor')::numeric) AS credit FROM reconforge.finance_posting_effects effect
            CROSS JOIN LATERAL jsonb_array_elements(effect.snapshot_json->'lines') line WHERE tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert totals["debit"] == totals["credit"] == 9600
        purchase = PostgresProcurementPartialRepository(connection, runtime.tenant).get(purchase["order"]["id"], actor=actor)
        assert (purchase["totals"]["accrued_minor"], purchase["totals"]["credited_minor"], purchase["totals"]["outstanding_minor"]) == ("2400", "2400", "0")
        assert purchase["invoices"][0]["native_status"] == "Credited"


def test_original_landed_charges_become_exact_expense_without_rewriting_paid_cash(runtime: ReceiptRuntime) -> None:
    from tests.test_postgres_landed_cost import phase as landed_phase
    from tests.test_postgres_landed_cost import prepare as landed_prepare
    purchase = create_order(runtime)
    landed = landed_phase(runtime, landed_phase(runtime, landed_prepare(runtime, purchase), "review", CHECKER), "post", POSTER)
    with runtime.actor(MAKER) as (connection, _, actor):
        purchase = PostgresProcurementPartialRepository(connection, runtime.tenant).get(purchase["order"]["id"], actor=actor)
    purchase = accrue_invoice(runtime, purchase, ((0, "10"),))
    plan = phase(runtime, phase(runtime, prepare(runtime, purchase), "review", CHECKER), "post", POSTER)
    assert (plan["credit_minor"], plan["inventory_removed_minor"], plan["charge_expense_minor"], plan["amount_minor"]) == ("12000", "12706", "706", "25412")
    assert len(plan["posting_effect_ids"]) == 3
    with runtime.actor(MAKER) as (connection, _, actor):
        from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
        assert PostgresLandedCostRepository(connection, runtime.tenant).get(landed["id"], actor=actor) == landed
        rows = connection.execute("""SELECT a.account_code,sum((line->>'debit_minor')::bigint-(line->>'credit_minor')::bigint) AS amount
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') line
            JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=line->>'account_id'
            WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        assert {row["account_code"]: int(row["amount"]) for row in rows} == {"AP": 0, "CASH": -1001, "CLEARING": -5000, "INVENTORY": 5295, "ADJUSTMENT": 706}
        assert connection.execute("SELECT sum(remaining_value_minor) AS amount FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["amount"] == 5295


@pytest.mark.parametrize("reviewed", [False, True])
def test_cancel_releases_unpaid_ap_claim_and_retains_original_inverse_and_ack(runtime: ReceiptRuntime, reviewed: bool) -> None:
    purchase = source(runtime)
    prepared = prepare(runtime, purchase)
    plan = phase(runtime, prepared, "review", CHECKER) if reviewed else prepared
    cancelled = phase(runtime, plan, "cancel", POSTER if reviewed else CHECKER)
    assert cancelled["status"] == "Cancelled" and not cancelled["posting_effect_ids"]
    before = snapshot(runtime)
    with pytest.raises(FinancePostingError), runtime.actor(POSTER) as (connection, _, actor):
        PostgresSupplierReturnsRepository(connection, runtime.tenant).post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="after-cancel-post", reason="Cannot post retained cancelled source", actor=actor)
    assert snapshot(runtime) == before
    pay_invoice(runtime, purchase["invoices"][0]["native_invoice_id"], 2400, "after-return-cancel", date="2026-10-06")
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        assert owner.get(cancelled["id"], actor=actor) == cancelled
        assert owner.prepare(preparation(purchase), command_id="sr-prepare", actor=actor) == prepared
        assert connection.execute("SELECT count(*) AS total FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s AND original_plan_id=%s", (runtime.tenant, prepared["source_snapshot"]["receipt"]["receipt_plan_id"])).fetchone()["total"] == 1


def test_paid_original_ap_refuses_supplier_return_without_any_draft_or_claim(runtime: ReceiptRuntime) -> None:
    purchase = source(runtime)
    pay_invoice(runtime, purchase["invoices"][0]["native_invoice_id"], 1, "prior-supplier-payment")
    before = snapshot(runtime)
    with pytest.raises(FinancePostingError, match="conflicts"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresSupplierReturnsRepository(connection, runtime.tenant).prepare(preparation(purchase), command_id="sr-prepare", actor=actor)
    assert snapshot(runtime) == before


def test_reviewed_cancellation_releases_same_original_source_for_one_fresh_posted_debit(runtime: ReceiptRuntime) -> None:
    purchase = source(runtime)
    prepared = prepare(runtime, purchase)
    cancelled = phase(runtime, phase(runtime, prepared, "review", CHECKER), "cancel", POSTER)
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        replacement = owner.prepare(preparation(purchase, "SR1-REPLACEMENT"), command_id="replacement-prepare", actor=actor)
        assert replacement["id"] != cancelled["id"] and replacement["receipt_id"] == cancelled["receipt_id"]
        assert owner.get(cancelled["id"], actor=actor) == cancelled
        assert owner.prepare(preparation(purchase), command_id="sr-prepare", actor=actor) == prepared
    posted = phase(runtime, phase(runtime, replacement, "review", CHECKER), "post", POSTER)
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        assert owner.get(cancelled["id"], actor=actor) == cancelled and owner.get(posted["id"], actor=actor) == posted
        assert connection.execute("SELECT count(*) FROM reconforge.ap_supplier_invoice_credits WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, cancelled["inverse_plan"]["plan_id"])).fetchone()[0] == 0
        assert connection.execute("SELECT sum(remaining_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0
        totals = connection.execute("""SELECT count(DISTINCT effect.id),sum((line->>'debit_minor')::numeric),sum((line->>'credit_minor')::numeric)
            FROM reconforge.finance_posting_effects effect CROSS JOIN LATERAL jsonb_array_elements(effect.snapshot_json->'lines') line WHERE tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert tuple(totals) == (4, 9600, 9600)


@pytest.mark.parametrize("operation,actor_name,reviewed", [("review", MAKER, False), ("post", MAKER, True), ("post", CHECKER, True), ("cancel", MAKER, False), ("cancel", CHECKER, True)])
def test_current_original_three_human_duties_are_inseparable(runtime: ReceiptRuntime, operation: str, actor_name: str, reviewed: bool) -> None:
    plan = prepare(runtime, source(runtime))
    if reviewed:
        plan = phase(runtime, plan, "review", CHECKER)
    before = snapshot(runtime)
    with pytest.raises(FinancePostingError, match="independent|third"), runtime.actor(actor_name) as (connection, _, actor):
        getattr(PostgresSupplierReturnsRepository(connection, runtime.tenant), operation)(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="wrong-duty", reason="Wrong current human cannot act", actor=actor)
    assert snapshot(runtime) == before


@pytest.mark.parametrize("attack", ["payload", "command", "receipt-claim", "early-credit", "fifo"])
def test_direct_sql_cannot_detach_original_inventory_payable_or_ack(runtime: ReceiptRuntime, attack: str) -> None:
    import psycopg
    plan = prepare(runtime, source(runtime))
    before = snapshot(runtime)
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.RaiseException)), runtime.actor(MAKER) as (connection, _, _):
        if attack == "payload":
            connection.execute("UPDATE reconforge.supplier_return_plans SET payload=jsonb_set(payload,'{credit_minor}','1') WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
        elif attack == "command":
            connection.execute("DELETE FROM reconforge.supplier_return_commands WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, plan["id"]))
        elif attack == "receipt-claim":
            connection.execute("UPDATE reconforge.procurement_partial_receipts SET supplier_return_owner_id=NULL WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["receipt_id"]))
        elif attack == "early-credit":
            connection.execute("UPDATE reconforge.ap_supplier_invoices SET status='Credited',row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["native_invoice_id"]))
        else:
            connection.execute("UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=0,remaining_value_minor=0 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["inverse_plan"]["artifacts"]["cost_layer_id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(runtime) == before


def test_arbitrary_generated_inverse_of_original_ap_requires_complete_supplier_owner(runtime: ReceiptRuntime) -> None:
    import psycopg
    purchase = source(runtime)
    before = snapshot(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="Original procurement AP inverse"), runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        original = owner._source(purchase["order"]["id"], purchase["receipts"][0]["id"], purchase["invoices"][0]["id"])
        owner._inverse(original["accrual_effect"], {**original["original_plan"]["scope"], "id": "UNRELATED-AP-INVERSE", "posting_date": "2026-10-05", "period_id": "period", "reason": "Raw SQL source escape"}, actor)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(runtime) == before


def test_unrelated_manual_reversal_needs_no_procurement_partial_invoice_select(runtime: ReceiptRuntime, receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
    from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository

    role = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    with psycopg.connect(receipt_database[0]) as admin:
        admin.execute(sql.SQL("REVOKE SELECT ON reconforge.procurement_partial_invoices FROM {}").format(sql.Identifier(role)))
    try:
        with runtime.actor(MAKER) as (connection, _, actor):
            entry = PostgresFinanceCoreRepository(connection, runtime.tenant).create_entry(
                entry_number="ORDINARY-MANUAL", organization_code="ORG", entity_code="ENTITY", workspace="work",
                period_id="period", journal_code="STOCK", posting_date="2026-10-05", description="Native finance-only manual source",
                lines=[{"account_code": "ADJUSTMENT", "debit": "1.00", "credit": "0"},
                       {"account_code": "CASH", "debit": "0", "credit": "1.00"}], actor_label=actor.username)
        with runtime.actor(CHECKER) as (connection, _, actor):
            finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
            posting = PostgresFinancePostingRepository(connection, runtime.tenant)
            finance.validate_entry(entry["id"], reason="Independent ordinary finance review", actor_label=actor.username)
            digest = posting.preview(entry["id"], actor=actor)["validation_digest"]
            original = posting.post(entry["id"], command_id="ordinary-manual-post", expected_validation_digest=digest,
                                    reason="Ordinary source publication", actor=actor)
        with runtime.actor(MAKER) as (connection, _, actor):
            reverse = PostgresFinancePostingRepository(connection, runtime.tenant).prepare_reversal(original["id"],
                command_id="ordinary-manual-inverse", entry_number="ORDINARY-MANUAL-INVERSE", period_id="period",
                posting_date="2026-10-05", reason="Finance-only original correction", actor=actor)
        with runtime.actor(CHECKER) as (connection, _, actor):
            finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
            posting = PostgresFinancePostingRepository(connection, runtime.tenant)
            finance.validate_entry(reverse["entry_id"], reason="Independent ordinary inverse review", actor_label=actor.username)
            inverse = posting.post(reverse["entry_id"], command_id="ordinary-inverse-post",
                expected_validation_digest=posting.preview(reverse["entry_id"], actor=actor)["validation_digest"],
                reason="Ordinary inverse publication", actor=actor)
            assert inverse["reverses_effect_id"] == original["id"]
    finally:
        with psycopg.connect(receipt_database[0]) as admin:
            admin.execute(sql.SQL("GRANT SELECT ON reconforge.procurement_partial_invoices TO {}").format(sql.Identifier(role)))


def test_failure_after_native_fifo_remove_rolls_back_every_financial_and_operational_effect(runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = phase(runtime, prepare(runtime, source(runtime)), "review", CHECKER)
    before = snapshot(runtime)
    with pytest.raises(RuntimeError, match="injected supplier AP boundary"), runtime.actor(POSTER) as (connection, _, actor):
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        def fail(*args: Any, **kwargs: Any) -> Any:
            # Native FIFO Remove already executed; fail before the AP inverse.
            raise RuntimeError("injected supplier AP boundary")
        monkeypatch.setattr(owner.owner.posting, "post", fail)
        owner.post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="fault-post", reason="Atomic supplier return fault", actor=actor)
    assert snapshot(runtime) == before
    assert phase(runtime, plan, "post", POSTER)["status"] == "Posted"


def assert_waiting(runtime: ReceiptRuntime, holder: int, waiter: int) -> None:
    import psycopg
    with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
        deadline = monotonic() + 10
        while monotonic() < deadline and holder not in observer.execute("SELECT pg_blocking_pids(%s)", (waiter,)).fetchone()[0]:
            sleep(0.02)
        assert holder in observer.execute("SELECT pg_blocking_pids(%s)", (waiter,)).fetchone()[0]


def test_payment_waits_for_supplier_claim_and_cannot_create_a_draft_after_return_admission(runtime: ReceiptRuntime) -> None:
    from reconforge.infrastructure.postgres_financial_installments import PostgresFinancialInstallmentsRepository
    from tests.test_postgres_financial_installments import preparation as payment_request
    purchase = source(runtime)
    started, pids = Event(), {}
    def payment() -> str:
        with runtime.actor(CHECKER) as (connection, _, actor):
            pids["payment"] = connection.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
            started.set()
            try:
                PostgresFinancialInstallmentsRepository(connection, runtime.tenant).prepare(payment_request(purchase["invoices"][0]["native_invoice_id"], 1), command_id="waiting-payment", actor=actor)
            except FinancePostingError:
                return "refused"
            return "prepared"
    with ThreadPoolExecutor(max_workers=1) as pool:
        with runtime.actor(MAKER) as (connection, _, actor):
            owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
            plan = owner.prepare(preparation(purchase), command_id="sr-prepare", actor=actor)
            holder = connection.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
            pending = pool.submit(payment)
            assert started.wait(10)
            assert_waiting(runtime, holder, pids["payment"])
        assert pending.result(timeout=30) == "refused"
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresSupplierReturnsRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == plan
        assert connection.execute("SELECT count(*) AS total FROM reconforge.financial_installment_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["total"] == 0


def test_receiving_waits_for_purchase_parent_before_binding_and_fifo_without_deadlock(runtime: ReceiptRuntime) -> None:
    from reconforge.domain.procurement_partial import PartialQuantityPreparation
    purchase = source(runtime)
    started, pids = Event(), {}
    def receiving() -> dict[str, Any]:
        with runtime.actor(CHECKER) as (connection, _, actor):
            pids["receipt"] = connection.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
            started.set()
            return PostgresProcurementPartialRepository(connection, runtime.tenant).prepare_receipt_line(purchase["order"]["id"], purchase["lines"][1]["id"],
                PartialQuantityPreparation(quantity="1.25", posting_date="2026-10-06", period_id="period", reason="Independent other original line"),
                expected_version=purchase["order"]["row_version"], command_id="waiting-other-receipt", actor=actor)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with runtime.actor(MAKER) as (connection, _, actor):
            plan = PostgresSupplierReturnsRepository(connection, runtime.tenant).prepare(preparation(purchase), command_id="sr-prepare", actor=actor)
            holder = connection.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
            pending = pool.submit(receiving)
            assert started.wait(10)
            assert_waiting(runtime, holder, pids["receipt"])
        received = pending.result(timeout=30)
        assert len(received["receipts"]) == 2 and received["receipts"][-1]["quantity_text"] == "1.25"
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresSupplierReturnsRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == plan


def test_exact_replay_rechecks_live_permission_and_three_hierarchy_grants(runtime: ReceiptRuntime) -> None:
    purchase = source(runtime)
    plan = prepare(runtime, purchase)
    with runtime.actor(CHECKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by=%s,revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='inventory.valuation.reverse.manage'", ("id-" + CHECKER, runtime.tenant))
    before = snapshot(runtime)
    with pytest.raises(FinancePostingError), runtime.actor(MAKER) as (connection, _, actor):
        PostgresSupplierReturnsRepository(connection, runtime.tenant).prepare(preparation(purchase), command_id="sr-prepare", actor=actor)
    assert snapshot(runtime) == before

    with runtime.actor(CHECKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.principal_scope_grants SET revoked_at=now(),revoked_by=%s,revocation_reason='access_change' WHERE tenant_id=%s AND principal_id=%s AND scope_type='legal_entity'", ("id-" + CHECKER, runtime.tenant, "id-" + MAKER))
    before = snapshot(runtime)
    with pytest.raises(FinancePostingError), runtime.actor(MAKER) as (connection, _, actor):
        PostgresSupplierReturnsRepository(connection, runtime.tenant).get(plan["id"], actor=actor)
    assert snapshot(runtime) == before


def test_original_purchase_evidence_and_retries_require_full_retained_money_authority(runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    import psycopg

    from reconforge.auth.policy import evaluate_principal_access
    from reconforge.infrastructure import postgres_operational_finance as authority

    purchase = source(runtime)
    plan = prepare(runtime, purchase)
    assert plan["amount_minor"] == "4800" and plan["source_snapshot"]["order"]["total_minor"] == 17000
    before = snapshot(runtime)
    ceiling = Decimal("50.00")
    observed: list[Decimal | None] = []

    def governed_policy(principal: Any, **context: Any) -> Any:
        observed.append(context.get("amount"))
        return evaluate_principal_access(principal, maximum_amount=ceiling, **context)

    monkeypatch.setattr(authority, "evaluate_principal_access", governed_policy)

    def refuse_original_evidence() -> None:
        with runtime.actor(MAKER) as (connection, _, actor):
            owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
            for operation in (lambda: owner.get(plan["id"], actor=actor),
                              lambda: owner.list_plans(purchase["order"]["id"], actor=actor),
                              lambda: owner.prepare(preparation(purchase), command_id="sr-prepare", actor=actor),
                              lambda: owner.prepare(preparation(purchase, "SR1-NEW-NARROW"), command_id="new-narrow", actor=actor)):
                with pytest.raises(FinancePostingError, match="authorization"):
                    operation()
        with pytest.raises(FinancePostingError, match="authorization"), runtime.actor(CHECKER) as (connection, _, actor):
            PostgresSupplierReturnsRepository(connection, runtime.tenant).review(plan["id"],
                expected_plan_digest=plan["plan_digest"], command_id="narrow-review", reason="Narrow source authority refused", actor=actor)

    refuse_original_evidence()
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("SET LOCAL session_replication_role=replica")
        admin.execute("UPDATE reconforge.currencies SET minor_units=3 WHERE tenant_id=%s AND code='USD'", (runtime.tenant,))
    try:
        refuse_original_evidence()
    finally:
        with psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute("SET LOCAL session_replication_role=replica")
            admin.execute("UPDATE reconforge.currencies SET minor_units=2 WHERE tenant_id=%s AND code='USD'", (runtime.tenant,))
    assert snapshot(runtime) == before
    ceiling = Decimal("200.00")
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresSupplierReturnsRepository(connection, runtime.tenant)
        assert owner.get(plan["id"], actor=actor) == plan
        assert owner.prepare(preparation(purchase), command_id="sr-prepare", actor=actor) == plan
    assert Decimal("170.00") in observed and Decimal("17.000") not in observed


def test_ordinary_receiving_accrual_and_payment_require_no_new_supplier_owner_select(runtime: ReceiptRuntime, receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql
    owned = prepare(runtime, source(runtime))
    role = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    tables = ("supplier_return_plans", "supplier_return_events", "supplier_return_commands", "ap_supplier_invoice_credits")
    with psycopg.connect(receipt_database[0]) as admin:
        for table in tables:
            admin.execute(sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(role)))
    try:
        ordinary = receive_line(runtime, create_order(runtime, "ORDINARY-WITHOUT-SR-READ"), 0, "1", date="2026-10-06")
        ordinary = accrue_invoice(runtime, ordinary, ((0, "1"),), date="2026-10-06")
        pay_invoice(runtime, ordinary["invoices"][0]["native_invoice_id"], 1200, "ordinary-limited-sr", date="2026-10-06")
        with runtime.actor(MAKER) as (connection, _, actor):
            assert PostgresProcurementPartialRepository(connection, runtime.tenant).get(ordinary["order"]["id"], actor=actor)["totals"]["outstanding_minor"] == "0"
        with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.actor(MAKER) as (connection, _, actor):
            PostgresSupplierReturnsRepository(connection, runtime.tenant).get(owned["id"], actor=actor)
    finally:
        with psycopg.connect(receipt_database[0]) as admin:
            for table in tables:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(role)))


def test_actual_ordered_empty_rollback_and_populated_refusal_keep_original_native_history() -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path

    import psycopg
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from psycopg import sql

    from tests.test_postgres_inventory_receipt_posting import receipt_database as native_database
    delegated = native_database.__wrapped__()
    try:
        database = next(delegated)
        selected = runtime.__wrapped__(database)
        purchase = source(selected)
        before = snapshot(selected)
        root = Path(__file__).resolve().parents[1]
        predecessor = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_revision("0130_pg_supplier_returns").down_revision
        env = {**os.environ, "RECONFORGE_POSTGRES_DSN": database[0]}
        for operation, target in (("downgrade", predecessor), ("upgrade", "head")):
            result = subprocess.run([sys.executable, "-m", "alembic", operation, target], cwd=root, env=env, capture_output=True, text=True, timeout=180, check=False)
            assert result.returncode == 0, result.stderr[-3000:]
        role = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
        with psycopg.connect(database[0]) as admin:
            for table in ("supplier_return_plans", "supplier_return_events", "supplier_return_commands", "ap_supplier_invoice_credits"):
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(role)))
        assert snapshot(selected) == before
        plan = prepare(selected, purchase)
        retained = snapshot(selected)
        refused = subprocess.run([sys.executable, "-m", "alembic", "downgrade", predecessor], cwd=root, env=env, capture_output=True, text=True, timeout=180, check=False)
        assert refused.returncode != 0 and "Retained supplier return evidence" in refused.stderr
        assert snapshot(selected) == retained
        with selected.actor(MAKER) as (connection, _, actor):
            assert PostgresSupplierReturnsRepository(connection, selected.tenant).get(plan["id"], actor=actor) == plan
    finally:
        delegated.close()
