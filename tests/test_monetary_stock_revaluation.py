"""Current-carrying closing vectors independent of original-rate paid-prefix math."""

from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.monetary_customer_returns import MonetaryHistory
from reconforge.domain.monetary_stock_revaluation import monetary_revaluation_equation
from reconforge.infrastructure.postgres_monetary_stock_sales import (
    READ,
    VALUATION_PERMISSIONS,
    PostgresMonetaryStockSalesRepository,
    _StockFxOwner,
)
from tests.test_monetary_customer_returns import DAY, append, original, rate


def source_for(history: MonetaryHistory) -> dict[str, Any]:
    source = history.source
    return {"stock_order_id": source.source_order_id, "invoice_id": source.invoice_id,
            "foreign_policy": {"currency_code": source.transaction_policy.currency_code},
            "functional_policy": {"currency_code": source.functional_policy.currency_code},
            "foreign_gross_minor": sum(part.transaction_minor for part in source.components),
            "functional_gross_minor": sum(part.functional_minor for part in source.components),
            "request": {"receivable_account_code": "AR", "gain_account_code": "GAIN", "loss_account_code": "LOSS", "taxes": []}}


def test_credit_adjusted_560_foreign_700_carrying_is_valued_840_not_original_gross() -> None:
    history = MonetaryHistory(original(cost=12000))
    history, _ = append(history, "Collection", amount_minor=4000, settlement_rate=rate("1.3"))
    history, credit = append(history, "Return", quantity_scaled=6)
    assert (credit.after.transaction_outstanding_minor, credit.after.functional_outstanding_minor) == (560, 700)
    result = monetary_revaluation_equation(history, source_for(history), closing_rate=rate("1.5"), posting_date=DAY,
        unrealized_gain_account_code="UGAIN", unrealized_loss_account_code="ULOSS")
    assert (result["foreign_outstanding_minor"], result["historical_outstanding_minor"], result["valued_outstanding_minor"], result["unrealized_fx_minor"]) == (560, 700, 840, 140)
    assert result["lines"] == [{"account_code": "AR", "debit_minor": 140, "credit_minor": 0}, {"account_code": "UGAIN", "debit_minor": 0, "credit_minor": 140}]
    assert result["monetary_history_basis"]["history_version"] == 2
    assert history.events[-1] is credit


def test_real_closing_loss_may_reduce_valued_functional_amount_to_zero() -> None:
    history = MonetaryHistory(original(amount=1, exchange="1", quantity=1, cost=1, tax=None))
    result = monetary_revaluation_equation(history, source_for(history), closing_rate=rate("0.000001"), posting_date=DAY,
        unrealized_gain_account_code="UGAIN", unrealized_loss_account_code="ULOSS")
    assert (result["valued_outstanding_minor"], result["unrealized_fx_minor"], result["amount_minor"]) == (0, -1, 1)
    assert result["lines"] == [{"account_code": "AR", "debit_minor": 0, "credit_minor": 1}, {"account_code": "ULOSS", "debit_minor": 1, "credit_minor": 0}]


@pytest.mark.parametrize("change", ["foreign_identity", "invoice", "gross", "role", "rate", "zero_delta"])
def test_current_valuation_has_no_identity_fake_rate_source_swap_role_or_zero_journal_fallback(change: str) -> None:
    history = MonetaryHistory(original(foreign="USD", functional="USD") if change == "foreign_identity" else original())
    source = source_for(history)
    closing: Any = rate("1.5")
    gain = "UGAIN"
    if change == "invoice":
        source["invoice_id"] = "other-native-invoice"
    elif change == "gross":
        source["functional_gross_minor"] += 1
    elif change == "role":
        gain = "AR"
    elif change == "rate":
        closing = None
    elif change == "zero_delta":
        closing = rate("1.25")
    with pytest.raises(FinancePostingError):
        monetary_revaluation_equation(history, source, closing_rate=closing, posting_date=DAY,
            unrealized_gain_account_code=gain, unrealized_loss_account_code="ULOSS")


def test_valuation_permissions_keep_distinct_phase_ar_permissions_and_explicit_reversal_authority() -> None:
    assert {"read": READ, "prepare": READ | {"finance_core.manage", "receivables.manage"},
        "prepare_reversal": READ | {"finance_core.manage", "receivables.manage", "finance_core.reverse"},
        "review": READ | {"finance_core.validate", "receivables.approve"}, "post": READ | {"finance_core.post", "receivables.manage"}} == VALUATION_PERMISSIONS


def test_zero_valued_closing_still_authorizes_real_journal_turnover_without_fake_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
    owner = object.__new__(_StockFxOwner)
    native = {"schema_version": "operational-fx-stock-source-v2", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
              "functional_policy": {"currency_precision": 2}}
    plan = {"kind": "revalue", "amount_minor": 1, "equation": {"historical_outstanding_minor": 1, "valued_outstanding_minor": 0}}
    calls = []
    monkeypatch.setattr(PostgresOperationalFxTaxRepository, "_authorize", lambda *args, **kwargs: calls.append(("original", kwargs)))
    monkeypatch.setattr(owner, "owner", SimpleNamespace(_actor=lambda actor, permission, scope, **kwargs: calls.append((permission, scope))), raising=False)
    from reconforge.domain.finance_posting import PostingActor
    owner._authorize(PostingActor("actor", "human", frozenset()), "finance_core.validate", native, plan)
    assert calls[-1] == ("finance_core.validate", {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "amount_minor": 1, "currency_precision": 2})
    assert calls[0] == ("original", {"mutation": True})
    native["schema_version"] = "operational-fx-source-v1"
    with pytest.raises(FinancePostingError):
        owner._authorize(PostingActor("actor", "human", frozenset()), "finance_core.validate", native, plan)


def test_new_stock_valuation_scope_permissions_precede_private_order_read(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    def denied(*args: Any, **kwargs: Any) -> None:
        assert kwargs["permissions"] == VALUATION_PERMISSIONS["prepare"]
        raise FinancePostingError("operational_actor_denied", "Withdrawn current financial authority")
    def private(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Private original loaded before current authority")
    monkeypatch.setattr(owner, "_authority_locks", denied)
    monkeypatch.setattr(owner, "_order", private)
    from reconforge.domain.finance_posting import PostingActor
    with pytest.raises(FinancePostingError) as caught:
        owner._valuation_authority("stock", PostingActor("actor", "human", frozenset()), "prepare")
    assert caught.value.code == "operational_actor_denied"
