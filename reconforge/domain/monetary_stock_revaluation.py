"""Closing valuation of the exact current dual-currency receivable carrying.

Historical collections and component credits already own their releases. This
adapter values the remaining monetary position with the existing FX conversion
kernel; it never reconstructs a fictitious original-rate cash prefix.
"""

import re
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.monetary_customer_returns import MonetaryHistory, replay_monetary_history
from reconforge.domain.operational_fx_tax import HistoricalRate, canonical_day, convert_minor, exact_minor


def monetary_revaluation_equation(history: MonetaryHistory, source: dict[str, Any], *, closing_rate: HistoricalRate,
                                 posting_date: str, unrealized_gain_account_code: str,
                                 unrealized_loss_account_code: str) -> dict[str, Any]:
    position, chain = replay_monetary_history(history)
    original = history.source
    day = canonical_day(posting_date, "closing valuation date")
    foreign_gross = exact_minor(source["foreign_gross_minor"], "original foreign gross")
    functional_gross = exact_minor(source["functional_gross_minor"], "original functional gross")
    foreign, functional = original.transaction_policy.currency_code, original.functional_policy.currency_code
    if (foreign == functional or type(closing_rate) is not HistoricalRate or day < original.posting_date
            or (history.events and day < history.events[-1].posting_date)
            or source.get("stock_order_id") != original.source_order_id or source.get("invoice_id") != original.invoice_id
            or source["foreign_policy"]["currency_code"] != foreign or source["functional_policy"]["currency_code"] != functional
            or foreign_gross != sum(component.transaction_minor for component in original.components)
            or functional_gross != sum(component.functional_minor for component in original.components)):
        raise FinancePostingError("stock_monetary_state_invalid", "The exact original foreign monetary source and current ordered carrying are required.")
    outstanding = exact_minor(position.transaction_outstanding_minor, "current outstanding foreign AR")
    carrying = exact_minor(position.functional_outstanding_minor, "current historical functional AR", zero=True)
    valued = exact_minor(convert_minor(outstanding, closing_rate.resolve(foreign, functional, original.registry_context, day),
                                      original.registry_context), "closing functional AR", zero=True)
    delta = valued - carrying
    amount = exact_minor(abs(delta), "nonzero current monetary valuation difference")
    gain, loss = unrealized_gain_account_code, unrealized_loss_account_code
    request = source["request"]
    forbidden = [value for key, value in request.items() if key.endswith("_account_code")]
    forbidden.extend(component["account_code"] for component in request["taxes"])
    if (gain == loss or any(type(code) is not str or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", code) is None
                           or code in forbidden for code in (gain, loss))):
        raise FinancePostingError("fx_account_invalid", "Unrealized roles require distinct canonical accounts outside the original economic roles.")
    return {"foreign_before_minor": foreign_gross - outstanding,
            "historical_before_minor": functional_gross - carrying,
            "foreign_outstanding_minor": outstanding, "historical_outstanding_minor": carrying,
            "valued_outstanding_minor": valued, "unrealized_fx_minor": delta, "closing_rate": closing_rate.payload(day),
            "unrealized_gain_account_code": gain, "unrealized_loss_account_code": loss, "amount_minor": amount,
            "monetary_history_basis": {"source_fingerprint": original.fingerprint, "history_version": len(history.events),
                                       "history_fingerprint": chain},
            "lines": [{"account_code": request["receivable_account_code"], "debit_minor": max(delta, 0), "credit_minor": max(-delta, 0)},
                      {"account_code": gain if delta > 0 else loss, "debit_minor": max(-delta, 0), "credit_minor": max(delta, 0)}]}
