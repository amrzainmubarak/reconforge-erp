"""Exact outstanding foreign monetary revaluation over retained native FX sources."""

import re
from typing import Any

from reconforge.domain.finance_posting import digest_payload, text
from reconforge.domain.operational_fx_tax import HistoricalRate, canonical_day, convert_minor, exact_minor, fail
from reconforge.utils.money import CurrencyRegistryContext


def revaluation_equation(source: dict[str, Any], *, foreign_before_minor: int, historical_before_minor: int,
                         closing_rate: HistoricalRate, posting_date: str, unrealized_gain_account_code: str,
                         unrealized_loss_account_code: str, context: CurrencyRegistryContext) -> dict[str, Any]:
    before = exact_minor(foreign_before_minor, "foreign paid before revaluation", zero=True)
    historical = exact_minor(historical_before_minor, "original AR released before revaluation", zero=True)
    request = source["request"]
    day = canonical_day(posting_date, "closing valuation date")
    if day < request["posting_date"]:
        fail("Closing valuation cannot precede its original foreign source.", "fx_state_invalid")
    foreign, functional = source["foreign_policy"]["currency_code"], source["functional_policy"]["currency_code"]
    original = HistoricalRate(**request["original_rate"]).resolve(foreign, functional, context, request["posting_date"])
    if convert_minor(before, original, context) != historical:
        fail("Closing valuation requires the exact cumulative original-rate release.", "fx_state_invalid")
    outstanding = exact_minor(source["foreign_gross_minor"] - before, "unsettled foreign monetary balance")
    carrying = exact_minor(source["functional_gross_minor"] - historical, "historical outstanding AR", zero=True)
    closing = closing_rate.resolve(foreign, functional, context, day)
    valued = exact_minor(convert_minor(outstanding, closing, context), "closing functional outstanding AR")
    delta = valued - carrying
    amount = exact_minor(abs(delta), "nonzero unrealized difference")
    accounts = [unrealized_gain_account_code, unrealized_loss_account_code]
    existing = [value for key, value in request.items() if key.endswith("_account_code")]
    existing += [component["account_code"] for component in request["taxes"]]
    if (len(set(accounts)) != 2 or any(account in existing for account in accounts)
            or any(re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", account) is None for account in accounts)):
        fail("Unrealized gain and loss require distinct canonical accounts outside the original accounting roles.", "fx_account_invalid")
    lines = [{"account_code": request["receivable_account_code"], "debit_minor": max(delta, 0), "credit_minor": max(-delta, 0)},
             {"account_code": accounts[0] if delta > 0 else accounts[1], "debit_minor": max(-delta, 0), "credit_minor": max(delta, 0)}]
    return {"foreign_before_minor": before, "historical_before_minor": historical, "foreign_outstanding_minor": outstanding,
            "historical_outstanding_minor": carrying, "valued_outstanding_minor": valued, "unrealized_fx_minor": delta,
            "closing_rate": closing_rate.payload(day), "unrealized_gain_account_code": accounts[0], "unrealized_loss_account_code": accounts[1],
            "amount_minor": amount, "lines": lines}


def reversal_equation(original: dict[str, Any]) -> dict[str, Any]:
    if original["kind"] != "revalue" or original["phase"] != 2 or not original["posting_effect_id"]:
        fail("Explicit revaluation reversal requires its exact posted original operation.", "fx_state_invalid")
    equation = original["equation"]
    return {"original_revaluation_id": text(original["id"], "original revaluation"), "original_plan_digest": original["plan_digest"],
            "original_posting_effect_id": original["posting_effect_id"], "original_equation_digest": digest_payload(equation),
            "unrealized_fx_minor": -equation["unrealized_fx_minor"], "amount_minor": equation["amount_minor"],
            "lines": [{"account_code": line["account_code"], "debit_minor": line["credit_minor"], "credit_minor": line["debit_minor"]}
                      for line in equation["lines"]]}
