"""Exact installment admission reuses the canonical operational money contract."""
from dataclasses import replace

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.finance_posting import FinancePostingError


def request() -> CommercialCollectionPreparation:
    return CommercialCollectionPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG",
        entity_code="ENTITY", source_id="invoice", journal_code="CASH", period_id="period", posting_date="2026-10-10",
        debit_account_code="CASH", credit_account_code="AR", reason="Independent collection", amount_minor=9007199254740993, receipt_number="RECEIPT-1")


def test_exact_large_integer_is_retained_without_float_or_js_rounding() -> None:
    assert request().payload()["amount_minor"] == 9007199254740993


@pytest.mark.parametrize("amount", [True, 1.1, "1", 0, -1, 9000000000000000001])
def test_invalid_installment_money_is_rejected(amount: object) -> None:
    with pytest.raises(FinancePostingError):
        replace(request(), amount_minor=amount).payload()  # type: ignore[arg-type]


def test_foreign_source_kind_and_malformed_date_are_rejected() -> None:
    with pytest.raises(FinancePostingError):
        replace(request(), source_kind="APPayment").payload()
    with pytest.raises(FinancePostingError):
        replace(request(), posting_date="2026-02-31").payload()
