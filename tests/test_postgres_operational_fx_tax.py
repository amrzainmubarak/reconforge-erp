"""Restricted live PostgreSQL FX source closure and independent rational oracles."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_fx_tax import ForeignInvoicePreparation, HistoricalRate, TaxComponent
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["pytestmark", "receipt_database"]


def fx_request(number: str = "SERVICE-1", *, net: int = 10001) -> ForeignInvoicePreparation:
    return ForeignInvoicePreparation(workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY",
        customer_code="FOREIGN", invoice_number=number, posting_date="2026-10-01", due_date="2026-10-31", period_id="period", journal_code="STOCK",
        foreign_currency_code="EUR", net_minor=net, original_rate=HistoricalRate("1.25", "Synthetic original spot", "2026-10-01T12:00:00Z"),
        country_code="EG", transaction_class="synthetic-service", taxes=(TaxComponent("SYNTHETIC-VAT", "EG", "synthetic-service", "2026-01-01", "2026-12-31", "0.14", "TAX", "Synthetic reviewed fraction", "2026-v1"),),
        receivable_account_code="AR", revenue_account_code="REVENUE", cash_account_code="CASH", gain_account_code="GAIN", loss_account_code="LOSS", reason="Synthetic retained foreign service")


def seed_fx_runtime(database: tuple[str, str]) -> ReceiptRuntime:
    runtime = create_receipt_runtime(database)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        connection.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'EUR','Euro',2)", (runtime.tenant,))
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        for account, kind in (("AR", "Asset"), ("REVENUE", "Income"), ("CASH", "Asset"), ("GAIN", "Income"), ("LOSS", "Expense"), ("TAX", "Liability")):
            finance.upsert_account(account_code=account, name=account, account_type=kind, chart_code="DEFAULT", workspace="work")
        identities = PostgresIdentityRepository(connection)
        for permission in ("finance_core.read", "receivables.read", "receivables.manage", "receivables.approve"):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        PostgresReceivablesRepository(connection, runtime.tenant).upsert_customer(customer_code="FOREIGN", name="Synthetic foreign customer", currency_code="EUR",
            credit_limit_minor=9_000_000_000_000_000_000, workspace="work", organization_code="ORG", entity_code="ENTITY")
    return runtime


@pytest.fixture
def fx_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return seed_fx_runtime(receipt_database)


def prepare_fx(runtime: ReceiptRuntime, request: ForeignInvoicePreparation | None = None) -> dict[str, Any]:
    request = request or fx_request()
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        result = repository.prepare_invoice(request, command_id="prepare-" + request.invoice_number, actor=actor)
        assert repository.prepare_invoice(request, command_id="prepare-" + request.invoice_number, actor=actor) == result
        return result


def finish_fx(runtime: ReceiptRuntime, plan: dict[str, Any]) -> dict[str, Any]:
    for name, operation in (("checker", "review"), ("poster", "post")):
        with runtime.actor(name) as (connection, _, actor):
            repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
            args = {"expected_plan_digest": plan["plan_digest"], "command_id": operation + "-" + plan["id"], "reason": "Independent FX equation " + operation, "actor": actor}
            result = getattr(repository, operation)(plan["id"], **args)
            assert getattr(repository, operation)(plan["id"], **args) == result
    return result


def settle_fx(runtime: ReceiptRuntime, source_id: str, amount: int, rate: str, day: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresOperationalFxTaxRepository(connection, runtime.tenant).prepare_settlement(source_id, foreign_minor=amount,
            settlement_rate=HistoricalRate(rate, "Synthetic settlement spot", day + "T12:00:00Z"), period_id="period", posting_date=day,
            reason="Synthetic partial foreign receipt", command_id="settle-" + day, actor=actor)


def native_balances(runtime: ReceiptRuntime) -> dict[str, int]:
    with runtime.actor("poster") as (connection, _, _):
        rows = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor)::bigint AS amount FROM reconforge.finance_posting_effects effect
            JOIN reconforge.finance_entry_lines l ON l.tenant_id=effect.tenant_id AND l.entry_id=effect.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE effect.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        return {row["account_code"]: row["amount"] for row in rows}


def rounded(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def test_foreign_tax_recognition_partial_gain_loss_and_full_native_ar_close(fx_runtime: ReceiptRuntime) -> None:
    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    net, tax = 10001, rounded(Fraction(10001) * Fraction("0.14"))
    gross = net + tax
    functional_gross = rounded(Fraction(gross) * Fraction("1.25"))
    first = finish_fx(runtime, settle_fx(runtime, initial["source_id"], 4000, "1.3", "2026-10-02"))
    second = finish_fx(runtime, settle_fx(runtime, initial["source_id"], gross - 4000, "1.2", "2026-10-03"))
    cash_first = rounded(Fraction(4000) * Fraction("1.3"))
    cash_second = rounded(Fraction(gross - 4000) * Fraction("1.2"))
    release_first = rounded(Fraction(4000) * Fraction("1.25"))
    release_second = functional_gross - release_first
    assert first["equation"]["realized_fx_minor"] == cash_first - release_first == 200
    assert second["equation"]["realized_fx_minor"] == cash_second - release_second < 0
    assert native_balances(runtime) == {"AR": 0, "REVENUE": -rounded(Fraction(net) * Fraction("1.25")),
        "TAX": -(functional_gross - rounded(Fraction(net) * Fraction("1.25"))), "CASH": cash_first + cash_second,
        "GAIN": -200, "LOSS": release_second - cash_second}
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        detail = repository.get(initial["source_id"], actor=actor)
        assert detail["foreign_gross_minor"] == gross and detail["functional_gross_minor"] == functional_gross
        assert detail["foreign_outstanding_minor"] == detail["functional_outstanding_minor"] == 0
        invoice = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(detail["invoice_id"])
        assert invoice["status"] == "Paid" and invoice["outstanding_minor"] == 0 and invoice["currency_code"] == "EUR"
        for plan in (initial, first, second):
            proof = repository.plan_evidence(plan["id"], actor=actor)
            for field, digest in (("canonical_source_json", detail["source_digest"]), ("canonical_plan_json", plan["plan_digest"]), ("canonical_snapshot_json", plan["validation_digest"])):
                assert hashlib.sha256(proof[field].encode()).hexdigest() == digest
            assert json.loads(proof["canonical_snapshot_json"]) == plan["snapshot"]
            assert proof["totals"]["debit_minor"] == proof["totals"]["credit_minor"]
            assert [phase["actor_id"] for phase in proof["phases"]] == ["maker", "checker", "poster", "poster"]
            assert proof["native_effect"]["id"] == plan["posting_effect_id"]
        assert len(detail["plans"]) == 3


def test_direct_sql_native_ar_state_allocation_and_detached_gl_are_refused(fx_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = fx_runtime
    plan = prepare_fx(runtime)
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="independent"):
        PostgresOperationalFxTaxRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="self", reason="Self attempt", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("checker") as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, runtime.tenant).validate_entry(plan["entry_id"], reason="Detached review", actor_label=actor.username)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    initial = finish_fx(runtime, plan)
    for statement in (
        "UPDATE reconforge.ar_invoices SET status='Cancelled' WHERE tenant_id=%s",
        "UPDATE reconforge.ar_invoices SET invoice_number='ESCAPED' WHERE tenant_id=%s",
        "UPDATE reconforge.operational_fx_sources SET payload=jsonb_set(payload,'{foreign_gross_minor}','1') WHERE tenant_id=%s",
        "UPDATE reconforge.operational_fx_commands SET response_json='{}' WHERE tenant_id=%s",
        "DELETE FROM reconforge.operational_fx_reviews WHERE tenant_id=%s",
    ):
        with pytest.raises(psycopg.Error), runtime.actor("poster") as (connection, _, _):
            connection.execute(statement, (runtime.tenant,))
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, actor):
        source = PostgresOperationalFxTaxRepository(connection, runtime.tenant).get(initial["source_id"], actor=actor)
        from reconforge.platform.receivables import ReceiptAllocationInput
        PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(receipt_number="BYPASS", customer_code="FOREIGN", receipt_date="2026-10-02", currency_code="EUR",
            amount_minor=1, allocations=[ReceiptAllocationInput(source["invoice_id"], 1)], workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    pending = settle_fx(runtime, initial["source_id"], 100, "1.3", "2026-10-02")
    with runtime.actor("checker") as (connection, _, actor):
        PostgresOperationalFxTaxRepository(connection, runtime.tenant).review(pending["id"], expected_plan_digest=pending["plan_digest"], reason="Review", command_id="review", actor=actor)
    with runtime.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError, match="owner"):
        PostgresFinancePostingRepository(connection, runtime.tenant).post(pending["entry_id"], expected_validation_digest=pending["validation_digest"], command_id="bypass", reason="Detached post", actor=actor)
    with runtime.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError, match="source inverse"):
        PostgresFinancePostingRepository(connection, runtime.tenant).prepare_reversal(initial["posting_effect_id"], entry_number="DETACHED", period_id="period",
            posting_date="2026-10-04", reason="Detached inverse", command_id="inverse", actor=actor)


def test_late_native_post_failure_rolls_back_receipt_allocation_and_evidence(fx_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    plan = settle_fx(runtime, initial["source_id"], 3000, "1.3", "2026-10-02")
    with runtime.actor("checker") as (connection, _, actor):
        PostgresOperationalFxTaxRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Review", command_id="review", actor=actor)
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        original = repository._remember

        def fail_after_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            original(*args, **kwargs)
            raise RuntimeError("Synthetic lost owner after native publication")

        with monkeypatch.context() as patch:
            patch.setattr(repository, "_remember", fail_after_effect)
            with pytest.raises(RuntimeError, match="Synthetic lost"):
                repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Post", command_id="post", actor=actor)
        assert connection.execute("SELECT count(*) AS n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert repository.get(initial["source_id"], actor=actor)["foreign_paid_minor"] == 0
        posted = repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Post", command_id="post", actor=actor)
        assert posted["status"] == "Posted" and posted["receipt_id"] is not None


def test_concurrent_identical_prepare_and_competing_partial_settlements_are_serialized(fx_runtime: ReceiptRuntime) -> None:
    runtime = fx_runtime
    with ThreadPoolExecutor(max_workers=2) as executor:
        one, two = list(executor.map(lambda _: prepare_fx(runtime), range(2)))
    assert one == two
    initial = finish_fx(runtime, one)

    def propose(day: str) -> str:
        try:
            return settle_fx(runtime, initial["source_id"], 10000, "1.3", day)["id"]
        except FinancePostingError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(propose, ("2026-10-02", "2026-10-03")))
    assert sum(value.startswith("FX1-") for value in outcomes) == 1
    assert "fx_state_conflict" in outcomes


def test_original_policy_tax_scope_and_history_current_amount_authority(fx_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access
    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    first = finish_fx(runtime, settle_fx(runtime, initial["source_id"], 1, "1.3", "2026-10-02"))
    seen: list[Decimal | None] = []

    def ceiling(principal: Any, **context: Any) -> Any:
        seen.append(context.get("amount"))
        decision = evaluate_principal_access(principal, **context)
        return replace(decision, allowed=False) if context.get("amount") is not None and context["amount"] > Decimal("10") else decision

    with monkeypatch.context() as patch:
        patch.setattr(authority, "evaluate_principal_access", ceiling)
        with runtime.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError, match="authorization"):
            PostgresOperationalFxTaxRepository(connection, runtime.tenant).plan_evidence(first["id"], actor=actor)
        with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="authorization"):
            PostgresOperationalFxTaxRepository(connection, runtime.tenant).prepare_invoice(fx_request(), command_id="prepare-SERVICE-1", actor=actor)
    assert Decimal("114.01") in seen
    with runtime.actor("poster") as (connection, _, actor):
        proof = PostgresOperationalFxTaxRepository(connection, runtime.tenant).plan_evidence(initial["id"], actor=actor)
        tax = proof["source"]["tax_components"][0]
        policy = {key: value for key, value in tax.items() if key not in {"foreign_tax_minor", "functional_tax_minor", "policy_digest"}}
        assert hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == tax["policy_digest"]
        assert tax["version"] == "2026-v1" and tax["country_code"] == "EG" and tax["transaction_class"] == "synthetic-service"
