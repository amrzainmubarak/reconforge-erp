"""Installment admission keeps exact money and the legacy full contract separate."""

from dataclasses import replace

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.financial_installments import FinancialInstallmentPreparation
from reconforge.domain.operational_finance import OperationalFinancePreparation


def preparation() -> FinancialInstallmentPreparation:
    return FinancialInstallmentPreparation(workspace_id="WORK", organization_id="ORG", legal_entity_id="ENTITY",
        organization_code="ORG", entity_code="ENTITY", source_kind="APPayment", source_id="AP1", journal_code="GENERAL",
        period_id="PERIOD", posting_date="2026-10-09", debit_account_code="AP", credit_account_code="CASH",
        reason="Pay first approved installment", amount_minor=1)


@pytest.mark.parametrize("amount", [True, 0, -1, "1", 1.0, 9_000_000_000_000_000_001])
def test_installment_does_not_admit_coerced_or_unsupported_money(amount: object) -> None:
    with pytest.raises(FinancePostingError, match="exact positive"):
        replace(preparation(), amount_minor=amount).payload()  # type: ignore[arg-type]


def test_installment_keeps_explicit_small_amount_without_changing_full_source_arguments() -> None:
    request = replace(preparation(), amount_minor=37)
    payload = request.payload()
    assert payload.pop("amount_minor") == 37
    assert payload == OperationalFinancePreparation(**payload).payload()
    assert preparation().payload()["amount_minor"] == 1


def test_installment_cannot_impersonate_revenue_or_receipt() -> None:
    with pytest.raises(FinancePostingError):
        replace(preparation(), source_kind="ARReceipt").payload()
