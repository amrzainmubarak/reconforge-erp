"""Explicit commands for governed native partial customer credits.

Quantities are scaled at the immutable original delivery precision. These
commands carry intent; they neither authorize a person nor open a period.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from reconforge.domain.customer_returns import minor
from reconforge.domain.finance_posting import FinancePostingError, text


def _payload(value: Any) -> dict[str, Any]:
    result = asdict(value)
    for name, item in result.items():
        if name in {"quantity_scaled", "amount_minor", "expected_history_version"}:
            minor(item, name, zero=name == "expected_history_version")
            if name == "expected_history_version" and item >= 256:
                raise FinancePostingError("customer_partial_return_history_full", "The finite history budget is exhausted.")
        else:
            if type(item) is not str or text(item, name, maximum=500 if name == "reason" else 160) != item:
                raise FinancePostingError("customer_partial_return_request_invalid", "Exact command text is required.")
    if date.fromisoformat(result["posting_date"]).isoformat() != result["posting_date"]:
        raise FinancePostingError("customer_partial_return_date_invalid", "Exact ISO posting date is required.")
    return result


@dataclass(frozen=True)
class CustomerPartialReturnPreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    source_order_id: str
    quantity_scaled: int
    period_id: str
    posting_date: str
    journal_code: str
    refund_liability_account_code: str
    cash_account_code: str
    reason: str
    expected_history_version: int

    def payload(self) -> dict[str, Any]:
        return _payload(self)


@dataclass(frozen=True)
class CustomerPartialRefundPreparation:
    return_id: str
    amount_minor: int
    period_id: str
    posting_date: str
    reason: str
    expected_history_version: int

    def payload(self) -> dict[str, Any]:
        return _payload(self)


@dataclass(frozen=True)
class CustomerPartialReversePreparation:
    original_id: str
    period_id: str
    posting_date: str
    reason: str
    expected_history_version: int

    def payload(self) -> dict[str, Any]:
        return _payload(self)
