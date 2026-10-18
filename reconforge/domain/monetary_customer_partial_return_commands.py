"""Explicit intent for the fixed native monetary Stock return protocol."""

from dataclasses import asdict, dataclass
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.operational_fx_tax import HistoricalRate, canonical_day, exact_minor


def _payload(value: Any) -> dict[str, Any]:
    result = asdict(value)
    for field, item in result.items():
        if field in {"quantity_scaled", "amount_minor", "expected_history_version"}:
            exact_minor(item, field, zero=field == "expected_history_version")
            if field == "expected_history_version" and item >= 256:
                raise FinancePostingError("monetary_return_history_full", "The finite original history is full.")
        elif field == "settlement_rate":
            rate = value.settlement_rate
            if rate is not None:
                if type(rate) is not HistoricalRate:
                    raise FinancePostingError("monetary_return_request_invalid", "An exact retained settlement rate is required.")
                result[field] = rate.payload(result["posting_date"])
        elif type(item) is not str or text(item, field, maximum=500 if field == "reason" else 160) != item:
            raise FinancePostingError("monetary_return_request_invalid", "Exact current command text is required.")
    canonical_day(result["posting_date"], "posting_date")
    return result


@dataclass(frozen=True, slots=True)
class MonetaryPartialReturnPreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    source_order_id: str
    quantity_scaled: int
    period_id: str
    posting_date: str
    reason: str
    expected_history_version: int

    def payload(self) -> dict[str, Any]:
        return _payload(self)


@dataclass(frozen=True, slots=True)
class MonetaryPartialRefundPreparation:
    return_id: str
    amount_minor: int
    period_id: str
    posting_date: str
    settlement_rate: HistoricalRate | None
    reason: str
    expected_history_version: int

    def payload(self) -> dict[str, Any]:
        return _payload(self)


@dataclass(frozen=True, slots=True)
class MonetaryPartialReversePreparation:
    original_id: str
    period_id: str
    posting_date: str
    reason: str
    expected_history_version: int

    def payload(self) -> dict[str, Any]:
        return _payload(self)
