"""Exact paired FX ownership, cumulative carry and explained translation."""

from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_fx import (
    elimination_equation,
    group_report,
    recognition_equation,
    revaluation_equation,
    reversal_equation,
    settlement_equation,
    translate_book,
)
from tests.intercompany_fx_fixture import preparation, rate, source_fixture


def equations() -> tuple[Any, ...]:
    source, context = source_fixture()
    recognition = recognition_equation(source["request"], context)
    cash_rates = {"seller": rate("1.3", "2026-10-04").payload("2026-10-04"),
                  "buyer": rate("0.78", "2026-10-04").payload("2026-10-04")}
    closing_rates = {"seller": rate("1.32", "2026-10-31").payload("2026-10-31"),
                     "buyer": rate("0.82", "2026-10-31").payload("2026-10-31")}
    settlement = settlement_equation(source, transaction_before_minor=0, transaction_minor=3000,
        posting_date="2026-10-04", rates=cash_rates, context=context)
    closing = revaluation_equation(source, transaction_before_minor=3000,
        posting_date="2026-10-31", rates=closing_rates, context=context)
    return source, context, recognition, settlement, closing, cash_rates, closing_rates


def translations() -> tuple[Any, ...]:
    source, context, initial, cash, closing, cash_rates, closing_rates = equations()
    result = {}
    for book in ("seller", "buyer"):
        contributions = []
        for index, (equation, day, retained_rate) in enumerate((
            (initial, "2026-10-03", source["request"][book + "_original_rate"]),
            (cash, "2026-10-04", cash_rates[book]), (closing, "2026-10-31", closing_rates[book]),
        )):
            for number, row in enumerate(equation["books"][book], 1):
                contributions.append({**row, "effect_id": f"native-{index}-{book}", "entry_id": f"entry-{index}-{book}",
                    "line_number": number, "legal_entity_id": source["request"][book]["legal_entity_id"],
                    "posting_date": day, "income_rate": retained_rate})
        result[book] = translate_book(source, book, contributions, closing_rate=closing_rates[book],
                                     as_of_date="2026-10-31", context=context)
    return source, result


def test_actual_up_fixture_recognition_partial_cash_realized_and_unrealized() -> None:
    _, _, recognition, cash, closing, _, _ = equations()
    assert recognition["positions"]["seller"]["original_functional_minor"] == 12501
    assert recognition["positions"]["buyer"]["original_functional_minor"] == 8001
    assert all(value["currency_rounding_policy"] == "ROUND_HALF_UP" for value in recognition["policies"].values())
    assert cash["positions"]["seller"]["historical_release_minor"] == 3750
    assert cash["positions"]["seller"]["functional_cash_minor"] == 3900
    assert cash["positions"]["seller"]["realized_fx_minor"] == 150
    assert cash["positions"]["buyer"]["historical_release_minor"] == 2400
    assert cash["positions"]["buyer"]["functional_cash_minor"] == 2340
    assert cash["positions"]["buyer"]["realized_fx_minor"] == 60
    assert closing["positions"]["seller"]["historical_outstanding_minor"] == 8751
    assert closing["positions"]["seller"]["valued_outstanding_minor"] == 9241
    assert closing["positions"]["seller"]["unrealized_fx_minor"] == 490
    assert closing["positions"]["buyer"]["historical_outstanding_minor"] == 5601
    assert closing["positions"]["buyer"]["valued_outstanding_minor"] == 5741
    assert closing["positions"]["buyer"]["unrealized_fx_minor"] == -140


def test_translated_native_membership_retains_nonzero_fx_and_cta() -> None:
    source, translated = translations()
    assert translated["seller"]["cta_minor"] == -531
    assert translated["buyer"]["cta_minor"] == 240
    elimination = elimination_equation(source, translated)
    assert elimination["translated_trade_minor"] == 10001
    assert elimination["translated_residual_minor"] == 7001
    assert elimination["positions"]["adjustment"]["amount_minor"] == 17002
    adjusted = [{**row, "effect_id": "native-elimination", "entry_id": "native-group", "line_number": number}
                for number, row in enumerate(elimination["books"]["adjustment"], 1)]
    report = group_report(source, translated, adjusted, plan_digest="b" * 64)
    assert report["income_statement"] == {"income_minor": 563, "expense_minor": 171, "result_minor": 392}
    assert report["cash_net_movement_minor"] == 101
    assert report["cta_minor"] == -291
    assert report["balance_sheet"] == {"assets_minor": 101, "liabilities_minor": 0, "equity_minor": -291,
        "accumulated_unclosed_result_minor": 392, "balanced": True}
    assert len({row["effect_id"] for row in adjusted}) == 1
    assert report["trial_balance"]
    assert all(sum(row["balance_minor"] for row in translated[book]["accounts"]) == 0 for book in translated)


@pytest.mark.parametrize("amount", [0, -1, True, 1.0, "10001", 4_500_000_000_000_000_001])
def test_invalid_transaction_minor_fails(amount: object) -> None:
    with pytest.raises(FinancePostingError):
        replace(preparation(), transaction_minor=amount).payload()  # type: ignore[arg-type]


@pytest.mark.parametrize("paid", [1, 2, 3, 7, 3000, 10000, 10001])
def test_cumulative_up_releases_conserve_original_carry_under_partitioning(paid: int) -> None:
    source, context = source_fixture()
    rates = {book: source["request"][book + "_original_rate"] for book in ("seller", "buyer")}
    first = settlement_equation(source, transaction_before_minor=0, transaction_minor=paid,
        posting_date="2026-10-03", rates=rates, context=context)
    original = recognition_equation(source["request"], context)
    if paid < 10001:
        last = settlement_equation(source, transaction_before_minor=paid, transaction_minor=10001-paid,
            posting_date="2026-10-03", rates=rates, context=context)
        for book in ("seller", "buyer"):
            assert first["positions"][book]["historical_release_minor"] + last["positions"][book]["historical_release_minor"] == original["positions"][book]["original_functional_minor"]
    else:
        assert all(first["positions"][book]["historical_after_minor"] == original["positions"][book]["original_functional_minor"] for book in rates)


def test_real_policy_half_up_tie_is_not_called_half_even() -> None:
    source, context = source_fixture()
    request = replace(preparation(amount=2), seller_original_rate=rate("1.25", "2026-10-03")).payload()
    assert recognition_equation(request, context)["positions"]["seller"]["original_functional_minor"] == 3
    rates = {book: source["request"][book + "_original_rate"] for book in ("seller", "buyer")}
    with pytest.raises(FinancePostingError, match="residual"):
        settlement_equation(source, transaction_before_minor=3000, transaction_minor=7002,
            posting_date="2026-10-03", rates=rates, context=context)


def test_inverse_requires_exact_posted_original_and_preserves_every_native_line() -> None:
    _, _, _, _, closing, _, _ = equations()
    original = {"id": "IC2-" + "a" * 32, "kind": "revalue", "phase": 2, "plan_digest": "b" * 64,
                "posting_effect_ids": {"seller": "native-seller", "buyer": "native-buyer"}, "equation": closing}
    inverse = reversal_equation(original)
    assert inverse["original_posting_effect_ids"] == original["posting_effect_ids"]
    for book, rows in closing["books"].items():
        for row, reversed_row in zip(rows, inverse["books"][book], strict=True):
            assert row["account_code"] == reversed_row["account_code"]
            assert (row["debit_minor"], row["credit_minor"]) == (reversed_row["credit_minor"], reversed_row["debit_minor"])
    with pytest.raises(FinancePostingError):
        reversal_equation({**original, "phase": 1})
