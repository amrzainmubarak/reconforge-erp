"""Real nonowner SQL native source inverse, partial refunds and attack closure."""

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.customer_returns import CustomerRefundPreparation, CustomerReturnPreparation
from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_returns import PERMISSIONS, PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.test_postgres_commercial_collections import complete, invoiced, prepare
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_sales import create_reserved_order, create_stock_runtime, execute

_ = receipt_database


def configure_runtime(runtime: ReceiptRuntime) -> None:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        PostgresFinanceCoreRepository(connection, runtime.tenant).upsert_account(account_code="REFUND", name="Customer refund obligation",
            account_type="Liability", normal_balance="Credit", workspace="work")


def create_runtime(database: tuple[str, str], paid: int = 10000, *, quantity: str | None = None) -> tuple[ReceiptRuntime, str, str]:
    runtime = create_stock_runtime(database)
    configure_runtime(runtime)
    if quantity is None:
        _, invoice_id = invoiced(runtime)
    else:
        sale = create_reserved_order(runtime, "RETURN-SOURCE", quantity)
        sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
        sale = execute(runtime, sale, "review-issue", "checker")
        sale = execute(runtime, sale, "deliver", "poster")
        args = SalesInvoicePreparation("RETURN-SOURCE-INVOICE", "2026-10-09", "2026-10-31", "SALES", "period", "AR", "REVENUE", "Original merchandise invoice").payload()
        args.pop("reason")
        sale = execute(runtime, sale, "prepare-invoice", "maker", args)
        sale = execute(runtime, sale, "review-invoice", "checker")
        sale = execute(runtime, sale, "invoice", "poster")
        invoice_id = sale["invoice_id"]
    if paid:
        complete(runtime, prepare(runtime, invoice_id, paid), "FIRST")
    with runtime.actor("maker") as (connection, _, _actor):
        order_id = connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND invoice_id=%s",
                                      (runtime.tenant, invoice_id)).fetchone()["id"]
    return runtime, order_id, invoice_id


def request(order_id: str) -> CustomerReturnPreparation:
    return CustomerReturnPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG",
        entity_code="ENTITY", source_order_id=order_id, period_id="period", posting_date="2026-10-10", journal_code="CASH",
        refund_liability_account_code="REFUND", cash_account_code="CASH", reason="Original complete customer return")


def prepare_return(runtime: ReceiptRuntime, order_id: str, command: str = "return-prepare") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        result = owner.prepare(request(order_id), command_id=command, actor=actor)
        assert owner.prepare(request(order_id), command_id=command, actor=actor) == result
        return result


def phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, who: str,
          command: str | None = None) -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        method = getattr(owner, operation)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": command or plan["id"] + ":" + operation,
                "reason": "Actual original-source " + operation, "actor": actor}
        result = method(plan["id"], **args)
        assert method(plan["id"], **args) == result
        return result


def refund(runtime: ReceiptRuntime, parent: dict[str, Any], amount: int, command: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        args = CustomerRefundPreparation(parent["id"], amount, "period", "2026-10-10", "Actual partial refund")
        result = owner.prepare_refund(args, command_id=command, actor=actor)
        assert owner.prepare_refund(args, command_id=command, actor=actor) == result
        return result


def balances(runtime: ReceiptRuntime) -> dict[str, int]:
    with runtime.actor("maker") as (connection, _, _actor):
        rows = connection.execute("""SELECT a.account_code,sum(l.debit_minor::numeric-l.credit_minor) value
            FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entry_lines l ON l.tenant_id=f.tenant_id AND l.entry_id=f.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE f.tenant_id=%s GROUP BY a.account_code""",
            (runtime.tenant,)).fetchall()
        return {row["account_code"]: int(row["value"]) for row in rows}


def retained_state(runtime: ReceiptRuntime) -> str:
    from psycopg import sql

    with runtime.actor("maker") as (connection, _, _actor):
        tables = connection.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema='reconforge'
            AND table_type='BASE TABLE' AND table_name ~ '^(customer_return_|stock_|finance_|ar_|inventory_|operational_finance_|domain_audit_|outbox_)'
            ORDER BY table_name""").fetchall()
        state = {}
        for table in tables:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r) v FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text")
                .format(sql.Identifier(table["table_name"])), (runtime.tenant,)).fetchall()
            state[table["table_name"]] = [row["v"] for row in rows]
        return digest_payload(state)


@pytest.mark.parametrize("paid", [0, 10000, 45000])
def test_whole_original_fifo_credit_and_two_partial_refunds_conserve_independent_financial_oracle(
    receipt_database: tuple[str, str], paid: int,
) -> None:
    runtime, order_id, invoice_id = create_runtime(receipt_database, paid)
    plan = prepare_return(runtime, order_id)
    assert plan["credit_minor"] == 45000 and plan["cogs_restored_minor"] == 12000
    assert plan["refund_entitlement_minor"] == paid and plan["receivable_released_minor"] == 45000 - paid
    plan = phase(runtime, phase(runtime, plan, "review", "checker"), "post", "poster")
    assert plan["status"] == "Posted" and len(plan["posting_effect_ids"]) == (3 if paid else 2)
    expected = {"AR": 0, "REVENUE": 0, "COGS": 0, "INVENTORY": 12000, "REFUND": -paid, "CASH": paid}
    actual = balances(runtime)
    for account, value in expected.items():
        assert actual.get(account, 0) == Fraction(value)
    with runtime.actor("maker") as (connection, _, actor):
        original = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(invoice_id)
        assert original["status"] == "Cancelled" and original["total_minor"] == 45000 and original["allocated_minor"] == paid
        assert original["outstanding_minor"] == 0 and original["refund_due_minor"] == paid and original["credited_minor"] == 45000
        layer = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s",
                                   (runtime.tenant,)).fetchone()
        assert (layer["q"], layer["v"]) == (10, 12000)
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == plan
    if paid:
        for index, amount in enumerate((paid // 3, paid - paid // 3)):
            installment = refund(runtime, plan, amount, "refund-prepare-" + str(index))
            phase(runtime, phase(runtime, installment, "review", "checker"), "post", "poster")
            paid -= amount
            current = balances(runtime)
            assert current["REFUND"] == -paid and current["CASH"] == paid and current["AR"] == 0
        with runtime.actor("maker") as (connection, _, _actor):
            assert PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(invoice_id)["refund_due_minor"] == 0


def test_raw_sql_cannot_cancel_original_or_post_reserved_inverse_without_stock_credit_liability(
    receipt_database: tuple[str, str],
) -> None:
    import psycopg

    runtime, order_id, invoice_id = create_runtime(receipt_database)
    before = retained_state(runtime)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.ar_invoices SET status='Cancelled' WHERE tenant_id=%s AND id=%s", (runtime.tenant, invoice_id))
    assert retained_state(runtime) == before
    with pytest.raises(psycopg.errors.CheckViolation, match="revenue inverse requires complete"), runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        source = owner._source(order_id, lock=False)
        args = {**request(order_id).payload(), "id": "UNRELATED-REVENUE-REVERSAL"}
        owner._inverse(source["revenue"], "UNRELATED-REVENUE-REVERSAL", args, actor)
    assert retained_state(runtime) == before
    plan = phase(runtime, prepare_return(runtime, order_id), "review", "checker")
    before = retained_state(runtime)
    with runtime.actor("poster") as (connection, _, actor):
        from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository

        with pytest.raises(FinancePostingError, match="complete original-source"):
            PostgresFinancePostingRepository(connection, runtime.tenant).post(plan["entries"][0]["entry_id"], command_id="raw-partial-inverse",
                expected_validation_digest=plan["entries"][0]["validation_digest"], reason="Incomplete direct inverse", actor=actor)
    assert retained_state(runtime) == before
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.customer_return_plans SET phase=2 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
    assert retained_state(runtime) == before


def test_late_stock_restoration_failure_rolls_back_every_native_row_and_lost_ack_race_has_one_effect(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, order_id, _invoice_id = create_runtime(receipt_database)
    plan = phase(runtime, prepare_return(runtime, order_id), "review", "checker")
    before = retained_state(runtime)
    from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository

    with monkeypatch.context() as failure:
        failure.setattr(PostgresFinancePostingRepository, "post", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Injected failure after FIFO restitution")))
        with pytest.raises(RuntimeError, match="after FIFO"):
            phase(runtime, plan, "post", "poster")
    assert retained_state(runtime) == before
    with ThreadPoolExecutor(max_workers=3) as executor:
        answers = list(executor.map(lambda _index: phase(runtime, plan, "post", "poster"), range(3)))
    assert answers[0] == answers[1] == answers[2]
    parent = answers[0]
    installment = refund(runtime, parent, 3000, "refund-1")
    with pytest.raises(FinancePostingError):
        refund(runtime, parent, 3000, "refund-2")
    reviewed = phase(runtime, installment, "review", "checker")
    with ThreadPoolExecutor(max_workers=3) as executor:
        returned = list(executor.map(lambda _index: phase(runtime, reviewed, "post", "poster"), range(3)))
    assert returned[0] == returned[1] == returned[2]
    assert balances(runtime)["REFUND"] == -7000


def test_cancel_releases_only_unposted_claim_retains_old_ack_and_current_revocation_denies_retry(
    receipt_database: tuple[str, str],
) -> None:
    runtime, order_id, invoice_id = create_runtime(receipt_database)
    plan = prepare_return(runtime, order_id)
    with pytest.raises(FinancePostingError):
        prepare(runtime, invoice_id, 1000, "AFTER-CLAIM")
    with pytest.raises(FinancePostingError):
        phase(runtime, plan, "review", "maker")
    reviewed = phase(runtime, plan, "review", "checker")
    with pytest.raises(FinancePostingError):
        phase(runtime, reviewed, "cancel", "checker")
    cancelled = phase(runtime, reviewed, "cancel", "poster")
    assert cancelled["status"] == "Cancelled" and cancelled["posting_effect_ids"] == []
    assert prepare_return(runtime, order_id) == plan
    complete(runtime, prepare(runtime, invoice_id, 1000, "REPLACEMENT"), "REPLACEMENT")
    replacement = prepare_return(runtime, order_id, "new-return")
    assert replacement["refund_entitlement_minor"] == 11000
    with runtime.actor("maker") as (connection, _, actor):
        connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by=%s,
            revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1
            WHERE tenant_id=%s AND permission_name='finance_core.reverse'""", (actor.user_id, runtime.tenant))
        with pytest.raises(FinancePostingError, match="denied"):
            PostgresCustomerReturnsRepository(connection, runtime.tenant).prepare(request(order_id), command_id="new-return", actor=actor)


def test_original_partial_delivery_cost_restores_after_later_sale_without_repricing_or_consumption_rewrite(
    receipt_database: tuple[str, str],
) -> None:
    runtime, original_id, _invoice = create_runtime(receipt_database, 0, quantity="5")
    subsequent = create_reserved_order(runtime, "LATER-SOURCE", "3")
    subsequent = execute(runtime, subsequent, "prepare-issue", "maker", {"posting_date": "2026-10-10", "period_id": "period", "policy_code": "FIFO"})
    subsequent = execute(runtime, subsequent, "review-issue", "checker")
    execute(runtime, subsequent, "deliver", "poster")
    plan = prepare_return(runtime, original_id)
    assert (plan["credit_minor"], plan["cogs_restored_minor"]) == (22500, 6000)
    phase(runtime, phase(runtime, plan, "review", "checker"), "post", "poster")
    with runtime.actor("maker") as (connection, _, _actor):
        layer = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        assert (layer["q"], layer["v"]) == (7, 8400)
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
    assert balances(runtime)["COGS"] == Fraction(3 * 1200)
    assert balances(runtime)["REVENUE"] == balances(runtime)["AR"] == 0
    resale = create_reserved_order(runtime, "RESTORED-RESALE", "7")
    resale = execute(runtime, resale, "prepare-issue", "maker", {"posting_date": "2026-10-11", "period_id": "period", "policy_code": "FIFO"})
    resale = execute(runtime, resale, "review-issue", "checker")
    execute(runtime, resale, "deliver", "poster")
    with runtime.actor("maker") as (connection, _, _actor):
        layer = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        assert (layer["q"], layer["v"]) == (0, 0)
    assert balances(runtime)["COGS"] == 12000


def test_forward_upgrade_retains_native_source_empty_rollback_and_populated_credit_refusal() -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_customer_returns_schema import DOWNGRADE_SQL, UPGRADE_SQL

    delegated = receipt_database.__wrapped__()
    database = next(delegated)
    try:
        runtime, source, _invoice = create_runtime(database, 0)
        before = retained_state(runtime)
        with psycopg.connect(runtime.admin_dsn) as admin:
            bodies = admin.execute("SELECT oid::regprocedure::text,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname IN ('stock_sales_close','stock_commerce_public','collection_close','collection_invoice_close','ops_close_plan','inventory_valuation_reversal_guard') ORDER BY proname").fetchall()
            admin.execute(DOWNGRADE_SQL)
            assert admin.execute("SELECT to_regclass('reconforge.customer_return_plans')").fetchone()[0] is None
            assert not any("customer_return_" in row[0] for row in admin.execute("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND prokind='f'").fetchall())
            admin.execute(UPGRADE_SQL)
            assert admin.execute("SELECT oid::regprocedure::text,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname IN ('stock_sales_close','stock_commerce_public','collection_close','collection_invoice_close','ops_close_plan','inventory_valuation_reversal_guard') ORDER BY proname").fetchall() == bodies
            app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
            for table in ("customer_return_plans", "customer_return_events", "customer_return_commands"):
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))
        assert retained_state(runtime) == before
        plan = prepare_return(runtime, source)
        with pytest.raises(psycopg.Error, match="refuses to discard"), psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute(DOWNGRADE_SQL)
        assert prepare_return(runtime, source) == plan
    finally:
        with pytest.raises(StopIteration):
            next(delegated)


def test_current_full_source_amount_policy_covers_prepare_ack_and_refund_child_evidence(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access

    runtime, source, _invoice = create_runtime(receipt_database)
    ceiling = Decimal("700.00")
    observed: list[Decimal | None] = []

    def governed_policy(principal: Any, **context: Any) -> Any:
        observed.append(context.get("amount"))
        return evaluate_principal_access(principal, maximum_amount=ceiling, **context)

    monkeypatch.setattr(authority, "evaluate_principal_access", governed_policy)
    plan = prepare_return(runtime, source)
    assert plan["amount_minor"] == 67000  # gross450 + original COGS120 + collected100
    before = retained_state(runtime)
    ceiling = Decimal("500.00")
    with pytest.raises(FinancePostingError, match="authorization"):
        prepare_return(runtime, source)
    assert retained_state(runtime) == before
    ceiling = Decimal("700.00")
    assert prepare_return(runtime, source) == plan
    parent = phase(runtime, phase(runtime, plan, "review", "checker"), "post", "poster")
    first = phase(runtime, phase(runtime, refund(runtime, parent, 3000, "policy-refund-1"), "review", "checker"), "post", "poster")
    child = refund(runtime, parent, 1000, "policy-refund-2")
    assert first["amount_minor"] == 3000 and child["amount_minor"] == 1000 and child["refunded_before_minor"] == 3000
    before = retained_state(runtime)
    ceiling = Decimal("20.00")  # child10 and earlier-refund30 do not authorize original source670
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        with pytest.raises(FinancePostingError, match="authorization"):
            repository.get(child["id"], actor=actor)
        with pytest.raises(FinancePostingError, match="authorization"):
            repository.prepare_refund(CustomerRefundPreparation(parent["id"], 1000, "period", "2026-10-10", "Actual partial refund"),
                                      command_id="policy-refund-2", actor=actor)
    with pytest.raises(FinancePostingError, match="authorization"):
        phase(runtime, child, "review", "checker")
    assert retained_state(runtime) == before
    ceiling = Decimal("700.00")
    with runtime.actor("maker") as (connection, _, actor):
        assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(child["id"], actor=actor) == child
    assert Decimal("450.00") in observed and Decimal("670.00") in observed


def test_ordinary_stock_invoice_and_collections_do_not_require_cr1_select_but_claimed_source_fails_closed(
    receipt_database: tuple[str, str],
) -> None:
    import psycopg
    from psycopg import sql

    runtime = create_stock_runtime(receipt_database)
    configure_runtime(runtime)
    app_role = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    tables = ("customer_return_plans", "customer_return_events", "customer_return_commands")

    def permission(verb: str) -> None:
        with psycopg.connect(runtime.admin_dsn) as admin:
            for table in tables:
                statement = sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}") if verb == "revoke" else sql.SQL("GRANT SELECT ON reconforge.{} TO {}")
                admin.execute(statement.format(sql.Identifier(table), sql.Identifier(app_role)))

    permission("revoke")
    try:
        order, invoice = invoiced(runtime)
        collection = complete(runtime, prepare(runtime, invoice, 10000), "RESTRICTED")
        with runtime.actor("maker") as (connection, _, actor):
            assert not connection.execute("SELECT has_table_privilege(current_user,'reconforge.customer_return_plans','SELECT') ok").fetchone()["ok"]
            assert not connection.execute("SELECT reconforge.customer_return_credited(%s,%s) v", (runtime.tenant, invoice)).fetchone()["v"]
            projection = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(invoice)
            assert projection["outstanding_minor"] == 35000 and projection["allocated_minor"] == 10000
        assert collection["phase"] == 2
        permission("grant")
        source_id = order["lines"][0]["tranches"][0]["id"]
        credited = phase(runtime, phase(runtime, prepare_return(runtime, source_id), "review", "checker"), "post", "poster")
        assert credited["phase"] == 2
        permission("revoke")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="customer_return_plans"), runtime.actor("maker") as (connection, _, _actor):
            connection.execute("SELECT reconforge.customer_return_credited(%s,%s)", (runtime.tenant, invoice))
    finally:
        permission("grant")


def test_charge_backed_original_fifo_return_preserves_landed_cost_and_restitutes_exact_charged_cost(
    receipt_database: tuple[str, str],
) -> None:
    from tests.test_postgres_landed_cost import CHECKER, MAKER, POSTER, create_multiline_runtime, create_order
    from tests.test_postgres_landed_cost import phase as landed_phase
    from tests.test_postgres_landed_cost import prepare as landed_prepare

    base = create_multiline_runtime(receipt_database)
    purchase = create_order(base, "RETURN-LANDED-ORIGINAL")
    landed = landed_phase(base, landed_phase(base, landed_prepare(base, purchase), "review", CHECKER), "post", POSTER)
    runtime = create_stock_runtime(receipt_database, base_runtime=base, seed_stock=False)
    configure_runtime(runtime)
    original, invoice = invoiced(runtime)
    complete(runtime, prepare(runtime, invoice, 10000), "CHARGED")
    source_id = original["lines"][0]["tranches"][0]["id"]
    plan = prepare_return(runtime, source_id)
    # Independent Hamilton integer/Fraction oracle for each retained charge.
    freight_item = Fraction(777 * 12000, 17000)
    duty_item = Fraction(224 * 12000, 17000)
    assert (freight_item.numerator // freight_item.denominator, duty_item.numerator // duty_item.denominator) == (548, 158)
    charged = 12000 + 548 + 158
    assert plan["cogs_restored_minor"] == charged == 12706
    assert plan["credit_minor"] == 45000 and plan["refund_entitlement_minor"] == 10000
    parent = phase(runtime, phase(runtime, plan, "review", "checker"), "post", "poster")
    for amount, command in ((3000, "charged-refund-1"), (7000, "charged-refund-2")):
        installment = refund(runtime, parent, amount, command)
        phase(runtime, phase(runtime, installment, "review", "checker"), "post", "poster")
    with runtime.actor(MAKER) as (connection, _, _actor):
        assert connection.execute("SELECT reconforge.landed_cost_ack(%s,%s,2) v", (runtime.tenant, landed["id"])).fetchone()["v"] == landed
        connection.execute("SELECT reconforge.landed_cost_close(%s,%s)", (runtime.tenant, landed["id"]))
        layers = connection.execute("""SELECT x.item_code,c.original_value_minor,c.remaining_quantity_scaled,c.remaining_value_minor
            FROM reconforge.inventory_cost_layers c JOIN reconforge.inventory_items x ON x.tenant_id=c.tenant_id AND x.id=c.item_id
            WHERE c.tenant_id=%s ORDER BY x.item_code""", (runtime.tenant,)).fetchall()
        assert [tuple(row) for row in layers] == [("ITEM", charged, 10, charged), ("WEIGHT", 5295, 250, 5295)]
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=%s AND effect_type='Restore'", (runtime.tenant,)).fetchone()["n"] == 1
    result = balances(runtime)
    assert result["COGS"] == result["REVENUE"] == result["AR"] == result["REFUND"] == 0
