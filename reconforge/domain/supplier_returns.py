"""Whole unused receipt returns against one original unpaid native AP invoice."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.inventory_receipt_posting import exact_date, exact_text


@dataclass(frozen=True, kw_only=True)
class SupplierReturnPreparation:
    order_id: str
    receipt_id: str
    invoice_id: str
    number: str
    period_id: str
    posting_date: str
    expense_account_code: str
    reason: str

    def payload(self) -> dict[str, Any]:
        result = asdict(self)
        for key in result:
            result[key] = exact_text(result[key], maximum=500 if key == "reason" else 140)
        result["posting_date"] = exact_date(self.posting_date)
        if not self.number.startswith("SR1-") or len(self.number) > 64:
            raise FinancePostingError("supplier_return_number_invalid", "Use a bounded SR1- supplier return number.")
        return result


def return_values(merchandise: int, capitalized: int) -> dict[str, int]:
    if (type(merchandise) is not int or type(capitalized) is not int
            or not 1 <= merchandise <= capitalized <= 4_500_000_000_000_000_000):
        raise FinancePostingError("supplier_return_value_invalid", "Original merchandise and capitalized cost must fit exact native financial limits.")
    return {"credit_minor": merchandise, "inventory_removed_minor": capitalized,
            "charge_expense_minor": capitalized - merchandise, "amount_minor": 2 * capitalized}
