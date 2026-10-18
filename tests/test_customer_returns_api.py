"""HTTP exact-money requests and source-preserving response projections."""

import pytest
from pydantic import ValidationError

from reconforge.api.routes.customer_returns import RefundRequest, ReturnRequest, project


@pytest.mark.parametrize("amount", [1, 1.1, True, "0", "01", "1e2", "1.00", "-1"])
def test_refund_http_contract_rejects_ambiguous_minor_units(amount: object) -> None:
    with pytest.raises(ValidationError):
        RefundRequest.model_validate({"command_id": "command", "amount_minor": amount, "period_id": "period", "posting_date": "2026-10-10", "reason": "Synthetic partial refund"})


def test_all_native_nested_money_and_quantity_project_as_exact_text() -> None:
    value = {"credit_minor": 9007199254740993, "source_snapshot": {"consumptions": [{"quantity_scaled": 9007199254740993, "value_minor": 12000}]}, "phase": 2}
    assert project(value) == {"credit_minor": "9007199254740993", "source_snapshot": {"consumptions": [{"quantity_scaled": "9007199254740993", "value_minor": "12000"}]}, "phase": 2}


def test_client_cannot_inject_authority_or_partial_quantities_into_whole_source_return() -> None:
    valid = {"command_id": "command", "source_order_id": "source", "period_id": "period", "posting_date": "2026-10-10", "journal_code": "CASH", "refund_liability_account_code": "REFUND", "cash_account_code": "CASH", "reason": "Whole original delivery"}
    assert ReturnRequest.model_validate(valid).source_order_id == "source"
    for extra in ({"quantity_scaled": "1"}, {"legal_entity_id": "foreign"}, {"amount_minor": "1"}, {"tax_minor": "1"}):
        with pytest.raises(ValidationError):
            ReturnRequest.model_validate({**valid, **extra})
