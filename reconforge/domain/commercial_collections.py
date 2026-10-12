"""Exact, reviewed installment request for an already recognized stock-sale invoice."""
from dataclasses import asdict, dataclass

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.domain.stock_sales import stock_code


@dataclass(frozen=True)
class CommercialCollectionPreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    source_id: str
    journal_code: str
    period_id: str
    posting_date: str
    debit_account_code: str
    credit_account_code: str
    reason: str
    amount_minor: int
    receipt_number: str
    source_kind: str = "ARReceipt"

    def payload(self) -> dict[str, object]:
        values = asdict(self)
        base = OperationalFinancePreparation(**{
            key: value for key, value in values.items() if key not in {"amount_minor", "receipt_number"}
        }).payload()
        if self.source_kind != "ARReceipt" or type(self.amount_minor) is not int or not (
            0 < self.amount_minor <= 9_000_000_000_000_000_000
        ):
            raise FinancePostingError("collection_amount_invalid", "An exact positive native AR installment is required.")
        return {**base, "amount_minor": self.amount_minor, "receipt_number": stock_code(self.receipt_number, "receipt number")}
