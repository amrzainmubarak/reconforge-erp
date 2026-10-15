"""Pure boundaries of fixed source discovery, authority and parent lock order.

These checks exercise adapters as a system under test. They do not replace
native RLS, SQL closure, finance effects or migration evidence.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.monetary_customer_returns import MonetaryHistory, apply_monetary_event, prepare_monetary_event
from reconforge.infrastructure.postgres_monetary_stock_sales import (
    OPERATION_PERMISSIONS,
    PostgresMonetaryStockSalesRepository,
    _StockFxOwner,
)
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.infrastructure.postgres_stock_sales import OPERATION_PERMISSIONS as LEGACY_PERMISSIONS
from reconforge.infrastructure.postgres_stock_sales import PostgresStockSalesRepository
from tests.test_monetary_customer_returns import DAY, original, rate


def policy(currency: str, precision: int) -> dict[str, Any]:
    return {"currency_code": currency, "precision": precision, "rounding_policy": "ROUND_HALF_UP",
            "registry_version": "1", "registry_digest": "a" * 64}


def source_row() -> dict[str, Any]:
    return {"id": "stock", "customer_id": "customer", "invoice_id": "invoice", "status": "Invoiced", "source": {
        "schema_version": "stock-sales-monetary-order-v2", "total_minor": 500, "unit_price_minor": 1000, "net_unit_price_minor": 500,
        "monetary_policy": policy("EUR", 2), "functional_policy": policy("KWD", 3)},
        "issue_plan": {"total_cost_minor": 7}}


def test_delegated_cash_prepare_and_review_require_real_receivables_rights() -> None:
    assert OPERATION_PERMISSIONS["prepare-collection"] == LEGACY_PERMISSIONS["prepare-collection"] | {"receivables.manage"}
    assert OPERATION_PERMISSIONS["review-collection"] == LEGACY_PERMISSIONS["review-collection"] | {"receivables.approve"}
    for name in set(LEGACY_PERMISSIONS) - {"prepare-collection", "review-collection"}:
        assert OPERATION_PERMISSIONS[name] == LEGACY_PERMISSIONS[name]
    assert "receivables.manage" not in LEGACY_PERMISSIONS["prepare-collection"]
    assert "receivables.approve" not in LEGACY_PERMISSIONS["review-collection"]


@pytest.mark.parametrize("operation", ["read", "prepare-invoice"])
def test_foreign_price_and_functional_cost_authority_are_never_mixed_or_maximized(
    operation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    calls: list[tuple[int, int, bool, bool]] = []

    def authorize(actor: Any, permission: str, scope: dict[str, Any], *, mutation: bool, allow_zero_amount: bool) -> None:
        calls.append((scope["amount_minor"], scope["currency_precision"], mutation, allow_zero_amount))

    owner.ops = SimpleNamespace(_actor=authorize)  # type: ignore[assignment]
    owner.connection = SimpleNamespace(execute=lambda *args: None)
    monkeypatch.setattr(owner, "_authority_locks", lambda *args, **kwargs: None)
    monkeypatch.setattr(owner, "_origin", lambda identifier: None)
    owner._actor(PostingActor("actor", "human", frozenset()), operation, source_row())
    assert {(amount, precision) for amount, precision, _, _ in calls} == ({(1000, 2), (7, 3)} if operation == "read" else {(1000, 2), (500, 2), (7, 3)})
    assert all(mutation == (operation != "read") and not allow_zero for _, _, mutation, allow_zero in calls)


def test_known_original_gross_is_authorized_in_each_currency_before_later_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    calls = []
    owner.ops = SimpleNamespace(_actor=lambda actor, permission, scope, **kwargs: calls.append((scope["amount_minor"], scope["currency_precision"])))  # type: ignore[assignment]
    owner.connection = SimpleNamespace(execute=lambda *args: None)
    monkeypatch.setattr(owner, "_authority_locks", lambda *args, **kwargs: None)
    monkeypatch.setattr(owner, "_origin", lambda identifier: {"payload": {"equation": {"foreign_gross_minor": 570, "functional_gross_minor": 7777}}})
    owner._actor(PostingActor("actor", "human", frozenset()), "prepare-invoice", source_row())
    assert set(calls) == {(1000, 2), (570, 2), (7777, 3), (7, 3)}


@pytest.mark.parametrize("share", [False, True])
def test_all_detail_and_mutation_paths_lock_customer_then_invoice_then_stock(share: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.tenant_id = "tenant"
    calls = []
    owner.connection = SimpleNamespace(execute=lambda sql, args: calls.append((sql, args)))
    monkeypatch.setattr(owner, "_order", lambda identifier, **kwargs: calls.append(("stock", kwargs)))
    owner._parents(source_row(), share=share)
    assert "ar_customers" in calls[0][0] and calls[0][1] == ("tenant", "customer")
    assert "ar_invoices" in calls[1][0] and calls[1][1] == ("tenant", "invoice")
    assert calls[2] == ("stock", {"lock": not share, "read_lock": share})
    assert all(("FOR SHARE" if share else "FOR UPDATE") in calls[index][0] for index in (0, 1))


@pytest.mark.parametrize("schema", ["stock-sales-monetary-order-v2", None, "stock-sales-order-v0"])
def test_old_stock_getter_refuses_new_or_unclassified_source_before_command_admission(schema: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresStockSalesRepository)
    owner.tenant_id = "tenant"
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    monkeypatch.setattr(owner, "_one", lambda *args: {"source": {"schema_version": schema}})
    with pytest.raises(FinancePostingError) as caught:
        owner._order("stock")
    assert caught.value.code == "stock_sales_protocol_conflict"


def test_old_fx_source_getter_refuses_monetary_stock_owner_before_parent_wait() -> None:
    owner = object.__new__(PostgresOperationalFxTaxRepository)
    owner.tenant_id = "tenant"
    cursor = SimpleNamespace(description=[SimpleNamespace(name="payload")], fetchall=lambda: [
        {"payload": {"schema_version": "operational-fx-stock-source-v2"}}])
    owner.connection = SimpleNamespace(execute=lambda *args: cursor)
    with pytest.raises(FinancePostingError) as caught:
        owner._peek("source", "fx-source")
    assert caught.value.code == "fx_source_protocol_conflict"


def test_default_foreign_owner_denies_nullable_journal_before_any_phase_mutation() -> None:
    owner = object.__new__(PostgresOperationalFxTaxRepository)
    for source_schema in ("operational-fx-source-v1", "operational-fx-stock-source-v2"):
        with pytest.raises(FinancePostingError) as caught:
            owner._admit_journal_presence({"schema_version": source_schema}, {"entry_id": None, "amount_minor": 0})
        assert caught.value.code == "fx_state_invalid"


def zero_collection(monkeypatch: pytest.MonkeyPatch) -> tuple[_StockFxOwner, dict[str, Any], dict[str, Any], MonetaryHistory]:
    source = original(amount=2, exchange="0.5", quantity=3, cost=0, tax=None)
    history = MonetaryHistory(source)
    first = prepare_monetary_event(history, "Collection", posting_date=DAY, amount_minor=1, settlement_rate=rate("0.5"))
    history = apply_monetary_event(history, first)
    pending = prepare_monetary_event(history, "Collection", posting_date=DAY, amount_minor=1, settlement_rate=rate("0.000001"))
    assert pending.monetary.functional_turnover_minor == 0
    owner = object.__new__(_StockFxOwner)
    owner.tenant_id = "tenant"
    owner.stock = SimpleNamespace(_origin=lambda identifier: {"id": "origin", "fx_source_id": "fx", "invoice_id": "invoice"},
                                  _history=lambda identifier: history)  # type: ignore[assignment]
    monkeypatch.setattr(owner, "_state", lambda source: {"active_revaluation_plan_id": None})
    from dataclasses import asdict
    native_source = {"id": "fx", "schema_version": "operational-fx-stock-source-v2", "stock_order_id": "stock", "invoice_id": "invoice"}
    plan = {"id": "FX1-" + "a" * 32, "schema_version": "operational-fx-stock-plan-v2", "kind": "settle", "source_id": "fx",
        "entry_id": None, "amount_minor": 0, "snapshot": None, "validation_digest": None, "posting_date": DAY,
        "equation": {"foreign_minor": 1, "monetary_event": asdict(pending), "lines": []}}
    return owner, native_source, plan, history


def test_new_fixed_owner_allows_only_proved_zero_local_foreign_cash_without_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    owner._admit_journal_presence(source, plan)


def test_new_zero_collection_refuses_active_closing_valuation_before_review_or_post(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    monkeypatch.setattr(owner, "_state", lambda source: {"active_revaluation_plan_id": "FX1-" + "c" * 32})
    with pytest.raises(FinancePostingError) as caught:
        owner._admit_journal_presence(source, plan)
    assert caught.value.code == "stock_monetary_state_conflict"


@pytest.mark.parametrize("changed", ["legacy", "recognize", "boolean", "fake_snapshot", "fake_line", "foreign_zero", "functional_cash"])
def test_zero_journal_has_no_legacy_missing_or_balanced_foreign_source_fallback(changed: str, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    if changed == "legacy":
        source["schema_version"] = "operational-fx-source-v1"
    elif changed == "recognize":
        plan["kind"] = "recognize"
    elif changed == "boolean":
        plan["amount_minor"] = False
    elif changed == "fake_snapshot":
        plan["snapshot"] = {}
    elif changed == "fake_line":
        plan["equation"]["lines"] = [{"debit_minor": 0, "credit_minor": 0}]
    elif changed == "foreign_zero":
        plan["equation"]["foreign_minor"] = 0
    else:
        plan["equation"]["monetary_event"]["monetary"]["functional_cash_minor"] = 1
    with pytest.raises(FinancePostingError):
        owner._admit_journal_presence(source, plan)


def test_retained_zero_ack_must_pin_its_native_history_member_and_can_survive_later_closing_valuation(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import asdict
    owner, source, plan, history = zero_collection(monkeypatch)
    pending = prepare_monetary_event(history, "Collection", posting_date=DAY, amount_minor=1, settlement_rate=rate("0.000001"))
    history = apply_monetary_event(history, pending)
    monkeypatch.setattr(owner.stock, "_history", lambda identifier: history)
    monkeypatch.setattr(owner, "_state", lambda source: {"active_revaluation_plan_id": "FX1-" + "c" * 32})
    calls = []
    def execute(sql: str, args: tuple[Any, ...]) -> Any:
        calls.append(args)
        return SimpleNamespace(fetchone=lambda: (1,))
    owner.connection = SimpleNamespace(execute=execute)
    owner._admit_journal_presence(source, plan)
    assert calls == [("tenant", "origin", 2, plan["id"])]
    assert plan["equation"]["monetary_event"] == asdict(pending)
    owner.connection = SimpleNamespace(execute=lambda sql, args: SimpleNamespace(fetchone=lambda: None))
    with pytest.raises(FinancePostingError):
        owner._admit_journal_presence(source, plan)
