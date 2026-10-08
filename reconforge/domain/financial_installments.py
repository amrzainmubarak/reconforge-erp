"""Exact installment admission; existing Finance Posting and AP own all effects."""

from dataclasses import asdict, dataclass

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_finance import OperationalFinancePreparation


@dataclass(frozen=True)
class FinancialInstallmentPreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    source_kind: str
    source_id: str
    journal_code: str
    period_id: str
    posting_date: str
    debit_account_code: str
    credit_account_code: str
    reason: str
    amount_minor: int

    def payload(self) -> dict[str, object]:
        base = OperationalFinancePreparation(**{
            key: value for key, value in asdict(self).items() if key != "amount_minor"
        }).payload()
        if self.source_kind != "APPayment" or type(self.amount_minor) is not int or not (
            0 < self.amount_minor <= 9_000_000_000_000_000_000
        ):
            raise FinancePostingError("installment_request_invalid", "An exact positive native AP installment is required.")
        return {**base, "amount_minor": self.amount_minor}
