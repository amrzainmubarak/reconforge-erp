"""Closed native-source admission for reviewed operational double entry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from reconforge.domain.finance_posting import FinancePostingError, text

SourceKind = Literal["ARInvoice", "ARReceipt", "APInvoice", "APPayment"]
SOURCE_KINDS = frozenset({"ARInvoice", "ARReceipt", "APInvoice", "APPayment"})
SOURCE_PERMISSIONS = {
    "ARInvoice": "receivables.approve",
    "ARReceipt": "receivables.manage",
    "APInvoice": "payables.approve",
    "APPayment": "payables.settle",
}


@dataclass(frozen=True)
class OperationalFinancePreparation:
    """A fixed two-account map over a native, exact, functional-currency invoice.

    Collection/payment sources identify the invoice, then require a real native
    receipt allocation/payment link in the same outer transaction as posting.
    No arbitrary source table, SQL, runtime plugin or caller-supplied amount.
    """

    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    source_kind: SourceKind
    source_id: str
    journal_code: str
    period_id: str
    posting_date: str
    debit_account_code: str
    credit_account_code: str
    reason: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        for key, value in result.items():
            if text(value, key, maximum=500 if key == "reason" else 160) != value:
                raise FinancePostingError("operational_request_invalid", "Source arguments must be canonical text.")
        if self.source_kind not in SOURCE_KINDS or self.debit_account_code == self.credit_account_code:
            raise FinancePostingError(
                "operational_request_invalid", "A native source and distinct account map are required."
            )
        try:
            if date.fromisoformat(self.posting_date).isoformat() != self.posting_date:
                raise ValueError("noncanonical date")
        except ValueError as exc:
            raise FinancePostingError("operational_request_invalid", "An exact ISO business date is required.") from exc
        return result


def exact_minor_text(value: int, precision: int) -> str:
    """Serialize captured minor units to the existing exact FinanceCore port."""
    if (
        type(value) is not int
        or not 0 < value <= 9_000_000_000_000_000_000
        or type(precision) is not int
        or not 0 <= precision <= 8
    ):
        raise FinancePostingError(
            "operational_amount_invalid", "Captured money requires bounded positive integer minor units."
        )
    factor = 10**precision
    return str(value) if precision == 0 else f"{value // factor}.{value % factor:0{precision}d}"
