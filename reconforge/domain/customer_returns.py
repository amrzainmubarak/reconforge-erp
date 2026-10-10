"""Whole original stock-tranche credits and exact customer refund entitlements."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, text

MAX_MINOR = 9_000_000_000_000_000_000


def minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        raise FinancePostingError("customer_return_request_invalid", f"{field} requires bounded integer minor units.")
    return value


def credit_entitlement(gross: int, collected: int, cogs: int) -> dict[str, int]:
    """A full source credit extinguishes AR and owes exactly retained collections."""
    minor(gross, "gross")
    minor(collected, "collected", zero=True)
    minor(cogs, "cogs")
    if collected > gross or gross + cogs + collected > MAX_MINOR:
        raise FinancePostingError("customer_return_amount_invalid", "Original amounts exceed bounded credit turnover.")
    return {"credit_minor": gross, "receivable_released_minor": gross - collected,
            "refund_entitlement_minor": collected, "cogs_restored_minor": cogs,
            "turnover_minor": gross + cogs + collected}


@dataclass(frozen=True)
class CustomerReturnPreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    source_order_id: str
    period_id: str
    posting_date: str
    journal_code: str
    refund_liability_account_code: str
    cash_account_code: str
    reason: str

    def payload(self) -> dict[str, Any]:
        value = {key: text(item, key, maximum=500 if key == "reason" else 160)
                 for key, item in asdict(self).items()}
        try:
            date.fromisoformat(self.posting_date)
        except ValueError as exc:
            raise FinancePostingError("customer_return_date_invalid", "Use an ISO posting date.") from exc
        if self.refund_liability_account_code == self.cash_account_code:
            raise FinancePostingError("customer_return_account_invalid", "Cash and refund liability must differ.")
        return value


@dataclass(frozen=True)
class CustomerRefundPreparation:
    return_id: str
    amount_minor: int
    period_id: str
    posting_date: str
    reason: str

    def payload(self) -> dict[str, Any]:
        minor(self.amount_minor, "amount_minor")
        value = asdict(self)
        for key in value.keys() - {"amount_minor"}:
            value[key] = text(value[key], key, maximum=500 if key == "reason" else 160)
        try:
            date.fromisoformat(self.posting_date)
        except ValueError as exc:
            raise FinancePostingError("customer_return_date_invalid", "Use an ISO refund date.") from exc
        return value
