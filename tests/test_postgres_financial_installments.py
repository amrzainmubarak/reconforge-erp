"""Actual partial AP payments, immutable phases, retry and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.financial_installments import FinancialInstallmentPreparation
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_financial_installments import PostgresFinancialInstallmentsRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, pytestmark, receipt_database
from tests.test_postgres_procurement_partial import (
    CHECKER,
    MAKER,
    POSTER,
    complete_partial_accrual_cycle,
    create_procurement_partial_runtime,
)

__all__ = ["receipt_database", "pytestmark"]


@pytest.fixture
def installment_runtime(receipt_database: tuple[str, str]) -> tuple[ReceiptRuntime, str]:
    runtime = create_procurement_partial_runtime(receipt_database)
    view = complete_partial_accrual_cycle(runtime)
    return runtime, view["invoices"][0]["native_invoice_id"]


def preparation(invoice_id: str, amount: int) -> FinancialInstallmentPreparation:
    return FinancialInstallmentPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity",
        organization_code="ORG", entity_code="ENTITY", source_kind="APPayment", source_id=invoice_id,
        journal_code="STOCK", period_id="period", posting_date="2026-10-03", debit_account_code="AP",
        credit_account_code="CASH", reason="Independently reviewed supplier installment", amount_minor=amount)


def prepare(runtime: ReceiptRuntime, invoice_id: str, amount: int, command: str = "first") -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresFinancialInstallmentsRepository(connection, runtime.tenant)
        result = repository.prepare(preparation(invoice_id, amount), command_id="prepare-" + command, actor=actor)
        assert repository.prepare(preparation(invoice_id, amount), command_id="prepare-" + command, actor=actor) == result
        return result


def review(runtime: ReceiptRuntime, plan: dict[str, Any], command: str = "first") -> dict[str, Any]:
    with runtime.actor(CHECKER) as (connection, _, actor):
        repository = PostgresFinancialInstallmentsRepository(connection, runtime.tenant)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": "review-" + command,
                "reason": "Verified payable and exact residual", "actor": actor}
        result = repository.review(plan["id"], **args)
        assert repository.review(plan["id"], **args) == result
        return result


def post(runtime: ReceiptRuntime, plan: dict[str, Any], command: str = "first") -> dict[str, Any]:
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresFinancialInstallmentsRepository(connection, runtime.tenant)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": "post-" + command,
                "reason": "Pay approved installment", "actor": actor}
        result = repository.post(plan["id"], **args)
        assert repository.post(plan["id"], **args) == result
        return result


def test_two_installments_close_the_same_real_native_invoice(installment_runtime: tuple[ReceiptRuntime, str]) -> None:
    runtime, invoice_id = installment_runtime
    first = post(runtime, review(runtime, prepare(runtime, invoice_id, 1500)))
    with runtime.actor(POSTER) as (connection, _, _):
        assert PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(invoice_id)["status"] == "Approved"
    second = post(runtime, review(runtime, prepare(runtime, invoice_id, 2100, "second"), "second"), "second")
    with runtime.actor(POSTER) as (connection, _, actor):
        assert PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(invoice_id)["status"] == "Paid"
        links = connection.execute("SELECT amount_minor FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s",
                                   (runtime.tenant, invoice_id)).fetchall()
        assert sorted(row["amount_minor"] for row in links) == [1500, 2100]
        assert PostgresFinancialInstallmentsRepository(connection, runtime.tenant).get(first["id"], actor=actor) == first
        assert second["allocated_before_minor"] == 1500
        assert first["posting_effect_id"] != second["posting_effect_id"]


def test_overpayment_pending_claim_and_self_review_are_refused(installment_runtime: tuple[ReceiptRuntime, str]) -> None:
    runtime, invoice_id = installment_runtime
    with pytest.raises(FinancePostingError, match="residual"):
        prepare(runtime, invoice_id, 3601)
    plan = prepare(runtime, invoice_id, 1500)
    with pytest.raises(FinancePostingError, match="pending"):
        prepare(runtime, invoice_id, 1500, "other")
    with runtime.actor(MAKER) as (connection, _, actor), pytest.raises(FinancePostingError, match="independent"):
        PostgresFinancialInstallmentsRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"],
            command_id="self-review", reason="Invalid self review", actor=actor)
    post(runtime, review(runtime, plan))
    with pytest.raises(FinancePostingError, match="residual"):
        prepare(runtime, invoice_id, 2101, "overspend")


def test_parallel_same_command_has_one_business_effect(installment_runtime: tuple[ReceiptRuntime, str]) -> None:
    runtime, invoice_id = installment_runtime
    plan = review(runtime, prepare(runtime, invoice_id, 1500))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(runtime, plan), range(2)))
    assert results[0] == results[1]
    with runtime.actor(POSTER) as (connection, _, _):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s",
                                  (runtime.tenant, invoice_id)).fetchone()["n"] == 1


@pytest.mark.parametrize("target", ["review", "post", "amount", "delete"])
def test_generic_and_raw_commands_cannot_detach_installment_phase(installment_runtime: tuple[ReceiptRuntime, str], target: str) -> None:
    import psycopg

    runtime, invoice_id = installment_runtime
    plan = prepare(runtime, invoice_id, 1500)
    if target == "post":
        plan = review(runtime, plan)
        with runtime.actor(POSTER) as (connection, _, actor), pytest.raises(FinancePostingError, match="owner"):
            PostgresFinancePostingRepository(connection, runtime.tenant).post(plan["entry_id"], command_id="generic",
                expected_validation_digest=plan["validation_digest"], reason="Detached public posting", actor=actor)
        return
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor(CHECKER) as (connection, _, actor):
        if target == "review":
            from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
            PostgresFinanceCoreRepository(connection, runtime.tenant).validate_entry(plan["entry_id"], reason="Detached review", actor_label=actor.username)
        elif target == "amount":
            connection.execute("UPDATE reconforge.financial_installment_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s AND id=%s",
                               (runtime.tenant, plan["id"]))
        else:
            connection.execute("DELETE FROM reconforge.financial_installment_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_changed_command_amount_cannot_replay_financial_ack(installment_runtime: tuple[ReceiptRuntime, str]) -> None:
    runtime, invoice_id = installment_runtime
    prepare(runtime, invoice_id, 1500)
    with runtime.actor(MAKER) as (connection, _, actor), pytest.raises(FinancePostingError, match="another"):
        PostgresFinancialInstallmentsRepository(connection, runtime.tenant).prepare(replace(preparation(invoice_id, 1500), amount_minor=1501),
            command_id="prepare-first", actor=actor)


def test_posted_installment_history_refuses_update_and_delete_with_exact_owner_constraint(
    installment_runtime: tuple[ReceiptRuntime, str],
) -> None:
    import psycopg
    from psycopg import sql

    runtime, invoice_id = installment_runtime
    posted = post(runtime, review(runtime, prepare(runtime, invoice_id, 3600)))
    tables = (
        "financial_installment_plans", "financial_installment_reviews", "financial_installment_links",
        "financial_installment_commands", "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions",
        "finance_posting_effects", "finance_posting_commands", "ap_supplier_invoices", "ap_supplier_invoice_lines",
        "ap_payment_links", "ap_idempotency_keys", "domain_audit_events", "domain_audit_ledger_state", "outbox_events",
    )
    with runtime.actor(POSTER) as (connection, _, actor):
        def retained_history() -> dict[str, list[str]]:
            return {
                table: [row["snapshot"] for row in connection.execute(sql.SQL(
                    'SELECT to_jsonb(history)::text AS snapshot FROM reconforge.{} history '
                    'WHERE tenant_id=%s ORDER BY to_jsonb(history)::text COLLATE "C"',
                ).format(sql.Identifier(table)), (runtime.tenant,)).fetchall()]
                for table in tables
            }

        assert PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(invoice_id)["status"] == "Paid"
        before = retained_history()
        assert len(before["financial_installment_reviews"]) == 1
        assert len(before["financial_installment_links"]) == 1
        assert len(before["financial_installment_commands"]) == 3
        for statement in (
            "UPDATE reconforge.financial_installment_reviews SET reason=reason || ' tamper' WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_installment_reviews WHERE tenant_id=%s",
            "UPDATE reconforge.financial_installment_links SET posted_actor_id='maker' WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_installment_links WHERE tenant_id=%s",
            "UPDATE reconforge.financial_installment_commands SET response_json='{}'::jsonb WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_installment_commands WHERE tenant_id=%s",
        ):
            with pytest.raises(psycopg.errors.CheckViolation) as refusal, connection.transaction():
                connection.execute(statement, (runtime.tenant,))
            assert refusal.value.sqlstate == "23514"
            assert refusal.value.diag.constraint_name == "financial_installment_owner_phase"
            assert retained_history() == before
        assert PostgresFinancialInstallmentsRepository(connection, runtime.tenant).get(posted["id"], actor=actor) == posted


@pytest.mark.parametrize("fault", ["native_account", "native_date", "missing_precision"])
def test_native_sql_closure_refuses_capture_faults_without_retained_effects(installment_runtime: tuple[ReceiptRuntime, str], fault: str) -> None:
    import psycopg

    from reconforge.domain.finance_posting import digest_payload

    runtime, invoice_id = installment_runtime
    with runtime.actor(MAKER) as (connection, _, _):
        before = connection.execute("SELECT count(*) AS n FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresFinancialInstallmentsRepository(connection, runtime.tenant)
        create = repository.owner.finance.create_entry
        event = repository.owner._event
        if fault in {"native_account", "native_date"}:
            def capture(**arguments: Any) -> Any:
                if fault == "native_account":
                    arguments["lines"][0]["account_code"] = "CLEARING"
                else:
                    arguments["posting_date"] = "2026-10-07"
                return create(**arguments)
            repository.owner.finance.create_entry = capture  # type: ignore[method-assign]
        else:
            def capture_event(plan: Any, action: str, event_actor: Any, metadata: Any) -> Any:
                if action == "financial_installment_prepared":
                    del plan["currency_precision"]
                    plan["plan_digest"] = digest_payload({key: value for key, value in plan.items() if key not in {"plan_digest", "validation_digest"}})
                    metadata["plan_digest"] = plan["plan_digest"]
                return event(plan, action, event_actor, metadata)
            repository.owner._event = capture_event  # type: ignore[method-assign]
        repository.prepare(preparation(invoice_id,1500),command_id="capture-fault",actor=actor)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor(MAKER) as (connection, _, _):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == before
        assert connection.execute("SELECT count(*) AS n FROM reconforge.financial_installment_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_late_installment_ack_failure_rolls_back_gl_allocation_and_source_phase(installment_runtime: tuple[ReceiptRuntime, str]) -> None:
    runtime, invoice_id = installment_runtime
    plan = review(runtime, prepare(runtime, invoice_id,1500))
    with runtime.actor(POSTER) as (connection, _, _):
        effects_before = connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
    with pytest.raises(RuntimeError,match="Synthetic late acknowledgement failure"), runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresFinancialInstallmentsRepository(connection, runtime.tenant)
        remember = repository._remember
        def fail_ack(*args: Any, **kwargs: Any) -> Any:
            remember(*args, **kwargs)
            raise RuntimeError("Synthetic late acknowledgement failure")
        repository._remember = fail_ack  # type: ignore[method-assign]
        repository.post(plan["id"],expected_plan_digest=plan["plan_digest"],command_id="post-fault",reason="Safe atomic failure",actor=actor)
    with runtime.actor(POSTER) as (connection, _, actor):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == effects_before
        assert connection.execute("SELECT count(*) AS n FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s", (runtime.tenant,invoice_id)).fetchone()["n"] == 0
        assert PostgresFinancialInstallmentsRepository(connection,runtime.tenant).get(plan["id"],actor=actor)["phase"] == 1
    assert post(runtime,plan)["phase"] == 2
