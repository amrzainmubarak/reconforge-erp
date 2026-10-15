"""Literal GL directions and omitted-zero membership for monetary corrections."""

from dataclasses import asdict
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.monetary_customer_returns import MonetaryHistory, prepare_monetary_event
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import correction_lines
from tests.test_monetary_customer_returns import DAY, append, original


def captured(source: Any) -> dict[str, Any]:
    roles = {name + "_account_id": name for name in ("receivable", "refund_liability", "gain", "loss", "inventory", "cogs", "cash")}
    accounts = {*roles.values(), *(part.account_id for part in source.components)}
    return {"roles": roles, "source": {"components": [asdict(part) for part in source.components]},
            "dimensions": {account: {"department": "original-sales"} for account in accounts}}


def amounts(journals: Any) -> list[tuple[str, list[tuple[str, int, int]]]]:
    return [(purpose, [(line["account_id"], line["debit_minor"], line["credit_minor"]) for line in lines]) for purpose, lines in journals]


def test_actual_original_components_and_historical_ar_form_two_exact_additive_journals() -> None:
    source = original()
    from tests.test_monetary_customer_returns import rate
    history, _ = append(MonetaryHistory(source), "Collection", amount_minor=4000, settlement_rate=rate("1.3"))
    credit = prepare_monetary_event(history, "Return", posting_date=DAY, quantity_scaled=5)
    journals = correction_lines(credit, captured(source))
    assert amounts(journals) == [("MerchandiseCredit", [("revenue-account", 6250, 0), ("tax-account-1", 875, 0), ("receivable", 0, 7125)]),
                                ("CostRestoration", [("inventory", 3000, 0), ("cogs", 0, 3000)])]
    assert all(line["dimensions"] == {"department": "original-sales"} for _, lines in journals for line in lines)


@pytest.mark.parametrize(("gross", "cost", "expected"), [(1, 1, []), (3, 1, ["MerchandiseCredit"]), (1, 3, ["CostRestoration"])])
def test_zero_legs_never_create_zero_entries_and_cost_only_keeps_its_real_slot(gross: int, cost: int, expected: list[str]) -> None:
    source = original(foreign="USD", functional="USD", amount=gross, quantity=3, cost=cost, tax=None)
    event = prepare_monetary_event(MonetaryHistory(source), "Return", posting_date=DAY, quantity_scaled=1)
    journals = correction_lines(event, captured(source))
    assert [purpose for purpose, _ in journals] == expected
    assert all(line["debit_minor"] + line["credit_minor"] > 0 for _, lines in journals for line in lines)


@pytest.mark.parametrize(("gross", "exchange", "expected"), [
    (1, "2", [("revenue-account", 1, 0), ("gain", 0, 1)]),
    (2, "0.5", [("loss", 1, 0), ("receivable", 0, 1)]),
])
def test_zero_currency_components_still_require_the_real_alignment_journal(gross: int, exchange: str, expected: Any) -> None:
    source = original(amount=gross, exchange=exchange, quantity=3, cost=0, tax=None)
    event = prepare_monetary_event(MonetaryHistory(source), "Return", posting_date=DAY, quantity_scaled=1)
    assert amounts(correction_lines(event, captured(source))) == [("MerchandiseCredit", expected)]
    assert event.monetary.transaction_refund_delta_minor == event.monetary.functional_refund_delta_minor == 0


def test_refund_spot_difference_is_a_real_cash_gain_and_does_not_reprice_the_original_credit() -> None:
    source = original()
    from tests.test_monetary_customer_returns import rate
    history, _ = append(MonetaryHistory(source), "Collection", amount_minor=11400, settlement_rate=rate("1.25"))
    history, _ = append(history, "Return", quantity_scaled=5)
    refund = prepare_monetary_event(history, "Refund", posting_date=DAY, amount_minor=5700, settlement_rate=rate("1.1"))
    assert amounts(correction_lines(refund, captured(source))) == [("Refund", [("refund_liability", 7125, 0), ("cash", 0, 6270), ("gain", 0, 855)])]


def test_inverse_uses_the_native_original_effect_and_never_a_new_forward_template() -> None:
    source = original()
    history, event = append(MonetaryHistory(source), "Return", quantity_scaled=5)
    inverse = prepare_monetary_event(history, "ReverseReturn", posting_date=DAY, quantity_scaled=5, original_sequence=event.sequence)
    with pytest.raises(FinancePostingError) as caught:
        correction_lines(inverse, captured(source))
    assert caught.value.code == "monetary_return_evidence_invalid"


def test_missing_captured_dimensions_are_not_silently_replaced_with_empty_dimensions() -> None:
    source = original()
    event = prepare_monetary_event(MonetaryHistory(source), "Return", posting_date=DAY, quantity_scaled=5)
    native = captured(source)
    del native["dimensions"]["revenue-account"]
    with pytest.raises(FinancePostingError) as caught:
        correction_lines(event, native)
    assert caught.value.code == "monetary_return_evidence_invalid"
