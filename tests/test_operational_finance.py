"""Native AR/AP operational source money admission is exact and closed."""

from dataclasses import replace

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_finance import OperationalFinancePreparation, exact_minor_text


def request() -> OperationalFinancePreparation:
    return OperationalFinancePreparation(
        "work",
        "org",
        "entity",
        "ORG",
        "ENTITY",
        "ARInvoice",
        "invoice",
        "STOCK",
        "period",
        "2026-10-08",
        "AR",
        "REVENUE",
        "Native source",
    )


@pytest.mark.parametrize(
    ("amount", "precision", "expected"),
    [(1, 0, "1"), (1, 3, "0.001"), (12000, 2, "120.00"), (9_000_000_000_000_000_000, 8, "90000000000.00000000")],
)
def test_minor_serialization(amount: int, precision: int, expected: str) -> None:
    assert exact_minor_text(amount, precision) == expected


@pytest.mark.parametrize(("amount", "precision"), [(True, 2), (1.1, 2), (0, 2), (-1, 2), (1, True), (1, 9)])
def test_reject_inexact_or_unsupported_money(amount: int, precision: int) -> None:
    with pytest.raises(FinancePostingError):
        exact_minor_text(amount, precision)


def test_closed_native_source_request() -> None:
    assert request().payload()["source_kind"] == "ARInvoice"
    for invalid in (
        replace(request(), source_kind="Arbitrary"),
        replace(request(), credit_account_code="AR"),
        replace(request(), posting_date="2026-1-1"),
        replace(request(), source_id=" invoice"),
    ):
        with pytest.raises(FinancePostingError):
            invalid.payload()
