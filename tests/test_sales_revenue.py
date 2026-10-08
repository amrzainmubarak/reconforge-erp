"""Exact service revenue pricing and closed public input contracts."""

from decimal import localcontext

import pytest
from pydantic import ValidationError

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.sales_revenue import SalesLine, SalesQuotation


def test_exact_discount_quantity_and_context_independent_large_amount() -> None:
    with localcontext() as context:
        context.prec = 6
        line = SalesLine("Service", "3", 9_007_199_254_740_993, 1250).priced()
    assert line["unit_price_minor"] == 7_881_299_347_898_369
    assert line["line_total_minor"] == 23_643_898_043_695_107
    assert line["discount_basis_points"] == 1250


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-1", "0", "1e3", "", "0.0000000000000000000000000000001"])
def test_bad_or_excess_precision_quantities_are_explicit_exceptions(quantity: str) -> None:
    with pytest.raises(FinancePostingError):
        SalesLine("Service", quantity, 10, 0).priced()


@pytest.mark.parametrize("unit,discount", [(1.2, 0), (True, 0), (0, 0), (100, -1), (100, 10000), (100, 1.2), (1, 9999)])
def test_invalid_or_zero_discounted_money_is_rejected(unit: object, discount: object) -> None:
    with pytest.raises(FinancePostingError):
        SalesLine("Service", "1", unit, discount).priced()  # type: ignore[arg-type]


def test_quotation_retains_reproducible_discount_policy() -> None:
    quotation = SalesQuotation(
        "Q-1",
        "C-1",
        "2026-10-08",
        "2026-10-31",
        "USD",
        (SalesLine("Consulting", "2.5", 1001, 1000), SalesLine("Support", "1", 1000)),
    )
    snapshot = quotation.snapshot()
    assert snapshot["total_minor"] == 3253
    assert snapshot["fulfillment_kind"] == "Service"
    assert snapshot["discount_policy"] == "per-unit-minor-half-up-v1"
    assert snapshot["digest"] == digest_payload({key: value for key, value in snapshot.items() if key != "digest"})


def test_currency_and_expired_definition_require_correct_inputs() -> None:
    with pytest.raises(FinancePostingError, match="validity"):
        SalesQuotation("Q", "C", "2026-10-08", "2026-10-07", "USD", (SalesLine("S", "1", 1),)).snapshot()
    with pytest.raises(FinancePostingError, match="Currency"):
        SalesQuotation("Q", "C", "2026-10-08", "2026-10-31", "US", (SalesLine("S", "1", 1),)).snapshot()


def test_public_contract_rejects_float_bool_money_and_extra_fields() -> None:
    from reconforge.api.routes.sales_revenue import LineRequest, VersionRequest

    for value in (1.5, 1, True, "1e2", "01", "-1"):
        with pytest.raises(ValidationError):
            LineRequest(description="S", quantity="1", unit_price_minor=value)
    with pytest.raises(ValidationError):
        VersionRequest(command_id="C", expected_version=True, reason="Reviewed")
    with pytest.raises(ValidationError):
        VersionRequest(command_id="C", expected_version=1, reason="Reviewed", bypass=True)
