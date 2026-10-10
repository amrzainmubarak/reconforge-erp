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
        source_id = order["lines"][0]["tranches"][0]["stock_order_id"]
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
    source_id = original["lines"][0]["tranches"][0]["stock_order_id"]
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
    assert result["INVENTORY"] == 18001 and result["CASH"] == -1001 and result["CLEARING"] == -17000


def test_cancelled_source_releases_future_cash_admission_and_posted_history_survives_inactive_accounts(
    receipt_database: tuple[str, str],
) -> None:
    from dataclasses import replace

    import psycopg

    from reconforge.domain.commercial_collections import CommercialCollectionPreparation
    from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
    from reconforge.infrastructure.postgres_receivables import PostgresReceivablesError

    runtime, source, invoice = create_runtime(receipt_database, 0)
    retained = prepare_return(runtime, source)
    cancelled = phase(runtime, phase(runtime, retained, "review", "checker"), "cancel", "poster")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        PostgresFinanceCoreRepository(connection, runtime.tenant).upsert_account(account_code="CASH2", name="Second collected cash",
            account_type="Asset", normal_balance="Debit", workspace="work")
    with runtime.actor("maker") as (connection, _, actor):
        args = CommercialCollectionPreparation("work", "org", "entity", "ORG", "ENTITY", invoice, "CASH", "period", "2026-10-10",
            "CASH2", "AR", "Different native cash after original claim release", 1000, "RELEASED-CASH2")
        collection = PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(args, command_id="released-cash-prepare", actor=actor)
    complete(runtime, collection, "RELEASED-CASH2")
    assert prepare_return(runtime, source) == retained

    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        assert owner.get(cancelled["id"], actor=actor) == cancelled
        replacement = owner.prepare(replace(request(source), cash_account_code="CASH2"), command_id="historical-replacement", actor=actor)
    parent = phase(runtime, phase(runtime, replacement, "review", "checker"), "post", "poster")
    installment = refund(runtime, parent, 1000, "historical-refund")
    phase(runtime, phase(runtime, installment, "review", "checker"), "post", "poster")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        connection.execute("UPDATE reconforge.finance_accounts SET active=FALSE,allow_posting=FALSE WHERE tenant_id=%s AND account_code IN('CASH2','REFUND')", (runtime.tenant,))
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
        assert owner.get(parent["id"], actor=actor) == parent
        assert PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(invoice)["refund_due_minor"] == 0
    # Restored administrator-damaged source must not turn native projection into
    # an unchecked credit. The invoker still rejects it before returning AR0.
    with psycopg.connect(runtime.admin_dsn) as admin:
        original = admin.execute("SELECT payload FROM reconforge.customer_return_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, parent["id"])).fetchone()[0]
        admin.execute("SET LOCAL session_replication_role='replica'")
        admin.execute("UPDATE reconforge.customer_return_plans SET payload=jsonb_set(payload,'{credit_minor}','1') WHERE tenant_id=%s AND id=%s", (runtime.tenant, parent["id"]))
    try:
        with pytest.raises(PostgresReceivablesError), runtime.actor("maker") as (connection, _, _actor):
            PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(invoice)
        with pytest.raises(psycopg.errors.CheckViolation, match="exact source and preparation evidence"), runtime.actor("maker") as (connection, _, _actor):
            connection.execute("SELECT reconforge.customer_return_projection(%s,%s)", (runtime.tenant, invoice))
    finally:
        from reconforge.domain.finance_posting import canonical_json

        with psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute("SET LOCAL session_replication_role='replica'")
            admin.execute("UPDATE reconforge.customer_return_plans SET payload=%s::jsonb WHERE tenant_id=%s AND id=%s", (canonical_json(original), runtime.tenant, parent["id"]))
    assert prepare_return(runtime, source) == retained


def test_original_return_and_new_issue_share_currency_admission_before_stock_and_fifo_locks(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    import time

    import psycopg

    from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
    from tests.test_postgres_stock_sales import repository

    runtime, source, _invoice = create_runtime(receipt_database, 0, quantity="5")
    parent = phase(runtime, prepare_return(runtime, source), "review", "checker")
    reserved = create_reserved_order(runtime, "AFTER-RETURN-LOCK", "3")
    acquired, release, attempting = threading.Event(), threading.Event(), threading.Event()
    state = threading.local()
    pids: dict[str, int] = {}
    original = FinancePolicyStore.lock_binding

    def hold_binding(store: FinancePolicyStore, workspace_id: str) -> None:
        original(store, workspace_id)
        if threading.current_thread().name.startswith("cr-original-post") and not getattr(state, "held", False):
            state.held = True
            acquired.set()
            assert release.wait(45), "Synthetic return binding coordinator timed out"

    def post_return() -> dict[str, Any]:
        with runtime.actor("poster") as (connection, _, actor):
            pids["return"] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            return PostgresCustomerReturnsRepository(connection, runtime.tenant).post(parent["id"],
                expected_plan_digest=parent["plan_digest"], command_id="return-binding-post",
                reason="Restore exact original cost before competing new issue", actor=actor)

    def prepare_issue() -> dict[str, Any]:
        with runtime.actor("maker") as (connection, _, actor):
            pids["issue"] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            attempting.set()
            return repository(connection, runtime).act(reserved["id"], "prepare-issue", expected_version=reserved["row_version"],
                command_id="new-issue-binding-prepare", reason="Retain FIFO cost after original restitution",
                parameters={"posting_date": "2026-10-10", "period_id": "period", "policy_code": "FIFO"}, actor=actor)

    with monkeypatch.context() as patch:
        patch.setattr(FinancePolicyStore, "lock_binding", hold_binding)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="cr-original-post") as returns, ThreadPoolExecutor(max_workers=1) as sales:
            returned = returns.submit(post_return)
            try:
                assert acquired.wait(30)
                issued = sales.submit(prepare_issue)
                assert attempting.wait(30)
                deadline = time.monotonic() + 15
                blocked = False
                with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
                    while time.monotonic() < deadline:
                        if pids["return"] in observer.execute("SELECT pg_blocking_pids(%s)", (pids["issue"],)).fetchone()[0]:
                            blocked = True
                            break
                        time.sleep(.05)
                    assert blocked, "New issue must wait on the return's canonical currency binding"
                    # A wait late in create_entry would still appear in
                    # pg_blocking_pids, while already holding these native rows.
                    with observer.transaction():
                        assert observer.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s FOR UPDATE NOWAIT",
                            (runtime.tenant, reserved["id"])).fetchone()
                        assert observer.execute("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s FOR UPDATE NOWAIT",
                            (runtime.tenant,)).fetchone()
                assert not returned.done() and not issued.done()
            finally:
                release.set()
            credited, proposed = returned.result(timeout=120), issued.result(timeout=120)
    assert credited["status"] == "Posted" and proposed["status"] == "IssuePrepared"
    assert int(proposed["cogs_minor"]) == int(Fraction(12000 * 3, 10)) == 3600
    proposed = execute(runtime, proposed, "review-issue", "checker")
    execute(runtime, proposed, "deliver", "poster")
    with runtime.actor("maker") as (connection, _, actor):
        layer = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s",
                                   (runtime.tenant,)).fetchone()
        assert (layer["q"], layer["v"]) == (7, 8400)
        assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(parent["id"], actor=actor) == credited
    assert balances(runtime) == {"AR": 0, "REVENUE": 0, "COGS": 3600, "INVENTORY": 8400, "CLEARING": -12000}


def test_native_stock_lost_ack_after_period_close_rechecks_current_authority_after_command_wait(
    receipt_database: tuple[str, str],
) -> None:
    import time

    import psycopg

    from reconforge.domain.finance_posting import canonical_json
    from tests.test_postgres_stock_sales import repository

    runtime, source, _invoice = create_runtime(receipt_database, 0, quantity="5")
    with runtime.actor("maker") as (connection, _, _actor):
        retained = connection.execute("SELECT command_id,request,result FROM reconforge.stock_sales_commands WHERE tenant_id=%s AND order_id=%s AND operation='prepare-issue'",
                                      (runtime.tenant, source)).fetchone()
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        connection.execute("UPDATE reconforge.fiscal_periods SET status='Closed' WHERE tenant_id=%s AND id='period'", (runtime.tenant,))
    pids: dict[str, int] = {}

    def replay() -> dict[str, Any]:
        with runtime.actor("maker") as (connection, _, actor):
            pids["replay"] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            payload = dict(retained["request"]["payload"])
            return repository(connection, runtime).act(source, "prepare-issue", expected_version=payload.pop("expected_version"),
                command_id=retained["command_id"], reason=payload.pop("reason"), parameters=payload, actor=actor)

    assert replay() == retained["result"]
    before = retained_state(runtime)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as blocker:
            holder = blocker.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            blocker.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("stock-command:" + canonical_json([runtime.tenant, "work", retained["command_id"]]),))
            attempt = workers.submit(replay)
            deadline = time.monotonic() + 20
            blocked = False
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
                while time.monotonic() < deadline:
                    if "replay" in pids and holder in observer.execute("SELECT pg_blocking_pids(%s)", (pids["replay"],)).fetchone()[0]:
                        blocked = True
                        break
                    time.sleep(.05)
            assert blocked, "Lost acknowledgement retry must actually wait on its native command lock"
            with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
                assert connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
                    revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change' WHERE tenant_id=%s
                    AND role_id IN(SELECT id FROM reconforge.identity_roles WHERE tenant_id=%s AND name='receipt-operator')
                    AND permission_name='sales.manage'""", (runtime.tenant, runtime.tenant)).rowcount == 1
        with pytest.raises(FinancePostingError):
            attempt.result(timeout=60)
    assert retained_state(runtime) == before


def test_below_cost_native_stock_source_reads_and_replays_require_retained_cogs_amount_authority(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    import psycopg

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access
    from reconforge.domain.stock_sales import StockOrder
    from tests.test_postgres_stock_sales import repository

    runtime = create_stock_runtime(receipt_database)
    with runtime.actor("maker") as (connection, _, actor):
        sale = repository(connection, runtime).create(StockOrder("BELOW-COST", "CUSTOMER", "BELOW-COST-SOURCE", "ITEM", "MAIN", "STOCK",
            "5", 1000, "USD", "2026-10-09", "Original sale below retained FIFO cost", 0), command_id="below-cost-create", actor=actor)
    sale = execute(runtime, sale, "submit", "maker")
    sale = execute(runtime, sale, "approve", "checker")
    sale = execute(runtime, sale, "reserve", "maker")
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    reviewed = execute(runtime, sale, "review-issue", "checker")
    delivered = execute(runtime, reviewed, "deliver", "poster")
    assert delivered["total_minor"] == "5000" and delivered["cogs_minor"] == "6000"
    before = retained_state(runtime)
    ceiling = Decimal("55.00")
    observed: list[Decimal | None] = []

    def governed_policy(principal: Any, **context: Any) -> Any:
        observed.append(context.get("amount"))
        return evaluate_principal_access(principal, maximum_amount=ceiling, **context)

    monkeypatch.setattr(authority, "evaluate_principal_access", governed_policy)

    def refuse_retained_source() -> None:
        with runtime.actor("maker") as (connection, _, actor):
            owner = repository(connection, runtime)
            with pytest.raises(FinancePostingError, match="authorization"):
                owner.get(delivered["id"], actor=actor)
            with pytest.raises(FinancePostingError, match="authorization"):
                owner.list(actor=actor)
        with pytest.raises(FinancePostingError, match="authorization"):
            execute(runtime, sale, "review-issue", "checker")
        with pytest.raises(FinancePostingError, match="authorization"):
            execute(runtime, reviewed, "deliver", "poster")

    refuse_retained_source()
    # Current catalog precision cannot reinterpret retained source60 as6 and
    # evade a55 ceiling after an administrator-damaged restore.
    with psycopg.connect(runtime.admin_dsn) as admin:
        old_precision = admin.execute("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code='USD'", (runtime.tenant,)).fetchone()[0]
        admin.execute("SET LOCAL session_replication_role='replica'")
        admin.execute("UPDATE reconforge.currencies SET minor_units=3 WHERE tenant_id=%s AND code='USD'", (runtime.tenant,))
    try:
        refuse_retained_source()
    finally:
        with psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute("SET LOCAL session_replication_role='replica'")
            admin.execute("UPDATE reconforge.currencies SET minor_units=%s WHERE tenant_id=%s AND code='USD'", (old_precision, runtime.tenant))
    assert retained_state(runtime) == before
    ceiling = Decimal("70.00")
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(delivered["id"], actor=actor) == delivered
    assert execute(runtime, sale, "review-issue", "checker") == reviewed
    assert execute(runtime, reviewed, "deliver", "poster") == delivered
    assert Decimal("60.00") in observed and Decimal("6.000") not in observed
