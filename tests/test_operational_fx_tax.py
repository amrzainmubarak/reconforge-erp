"""Independent rational oracles for native foreign receivables and dated taxes."""

from dataclasses import replace
from decimal import localcontext
from fractions import Fraction
from random import Random

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_fx_tax import (
    ForeignInvoicePreparation,
    HistoricalRate,
    TaxComponent,
    invoice_equation,
    settlement_equation,
)
from reconforge.utils.money import CurrencyRegistry, CurrencyRegistryContext, CurrencySpec


def invoice(*, foreign: str = "EUR", amount: int = 10001, rate: str = "1.123456", taxes: tuple[TaxComponent, ...] | None = None) -> ForeignInvoicePreparation:
    return ForeignInvoicePreparation(workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG",
        entity_code="ENTITY", customer_code="EUR-CUSTOMER", invoice_number="FX-INVOICE-1", posting_date="2026-10-10", due_date="2026-11-10",
        period_id="period", journal_code="GENERAL", foreign_currency_code=foreign, net_minor=amount,
        original_rate=HistoricalRate(rate, "Synthetic reviewed spot observation", "2026-10-10T09:00:00Z"),
        country_code="EG", transaction_class="Service", taxes=taxes if taxes is not None else (
            TaxComponent("synthetic-vat-v1", "EG", "Service", "2026-01-01", "2026-12-31", "0.14", "TAX", "Synthetic tax policy, not a statutory rate"),),
        receivable_account_code="AR", revenue_account_code="REVENUE", cash_account_code="CASH", gain_account_code="FXGAIN", loss_account_code="FXLOSS",
        reason="Synthetic governed foreign invoice")


def half_up(value: Fraction) -> int:
    assert value >= 0
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def translated(amount: int, rate: str, foreign_precision: int, functional_precision: int) -> int:
    return half_up(Fraction(amount) * Fraction(rate) * 10**functional_precision / 10**foreign_precision)


@pytest.mark.parametrize(("foreign", "functional", "foreign_scale", "functional_scale", "rate"), [
    ("EUR", "USD", 2, 2, "1.123456"), ("JPY", "KWD", 0, 3, "0.00205123"), ("KWD", "JPY", 3, 0, "492.123456789012"),
])
def test_currency_specific_tax_and_three_partial_settlements_match_rational_oracle(
    foreign: str, functional: str, foreign_scale: int, functional_scale: int, rate: str,
) -> None:
    context = CurrencyRegistryContext.from_installed()
    request = invoice(foreign=foreign, amount=10001, rate=rate)
    source = invoice_equation(request, functional, context)
    tax = half_up(Fraction(10001) * Fraction("0.14"))
    assert source["foreign_tax_minor"] == tax
    assert source["foreign_gross_minor"] == 10001 + tax
    assert source["functional_net_minor"] == translated(10001, rate, foreign_scale, functional_scale)
    assert source["functional_gross_minor"] == translated(10001 + tax, rate, foreign_scale, functional_scale)
    assert sum(row["debit_minor"] for row in source["lines"]) == sum(row["credit_minor"] for row in source["lines"])
    paid, released = 0, 0
    for amount, spot in [(3333, rate), (4444, rate), (10001 + tax - 7777, rate)]:
        result = settlement_equation(source, foreign_minor=amount, foreign_before_minor=paid, historical_before_minor=released,
            settlement_rate=HistoricalRate(spot, "Synthetic settlement spot", "2026-10-11T09:00:00Z"), posting_date="2026-10-11", context=context)
        assert result["historical_release_minor"] == translated(paid + amount, rate, foreign_scale, functional_scale) - released
        assert result["functional_cash_minor"] == translated(amount, spot, foreign_scale, functional_scale)
        assert result["realized_fx_minor"] == result["functional_cash_minor"] - result["historical_release_minor"]
        assert sum(row["debit_minor"] for row in result["lines"]) == sum(row["credit_minor"] for row in result["lines"])
        paid, released = result["foreign_after_minor"], result["historical_after_minor"]
    assert paid == source["foreign_gross_minor"] and released == source["functional_gross_minor"]


def test_realized_gain_and_loss_have_opposite_exact_native_accounting() -> None:
    context = CurrencyRegistryContext.from_installed()
    source = invoice_equation(invoice(amount=10001, rate="1.25", taxes=()), "USD", context)
    gain = settlement_equation(source, foreign_minor=4000, foreign_before_minor=0, historical_before_minor=0,
        settlement_rate=HistoricalRate("1.30", "Synthetic gain", "2026-10-11T00:00:00Z"), posting_date="2026-10-11", context=context)
    loss = settlement_equation(source, foreign_minor=6001, foreign_before_minor=4000, historical_before_minor=5000,
        settlement_rate=HistoricalRate("1.20", "Synthetic loss", "2026-10-12T00:00:00Z"), posting_date="2026-10-12", context=context)
    assert gain["realized_fx_minor"] == 200 and gain["lines"][-1] == {"account_code": "FXGAIN", "debit_minor": 0, "credit_minor": 200}
    assert loss["realized_fx_minor"] == -300 and loss["lines"][-1] == {"account_code": "FXLOSS", "debit_minor": 300, "credit_minor": 0}
    assert loss["historical_after_minor"] == source["functional_gross_minor"] == 12501


def test_ordered_tax_components_and_extreme_decimal_context_match_independent_fractions() -> None:
    random = Random(849)
    context = CurrencyRegistryContext.from_installed()
    taxes = (TaxComponent("tax-a-v1", "EG", "Service", "2026-01-01", "2026-12-31", "0.14", "TAXA", "Synthetic A"),
             TaxComponent("tax-b-v1", "EG", "Service", "2026-01-01", "2026-12-31", "0.025", "TAXB", "Synthetic B"))
    with localcontext() as decimal_context:
        decimal_context.prec = 6
        for _ in range(250):
            amount = random.randrange(1000, 10**15)
            rate = "1." + str(random.randrange(10**11, 10**12))
            source = invoice_equation(invoice(amount=amount, rate=rate, taxes=taxes), "KWD", context)
            prefix, functional_prefix = amount, translated(amount, rate, 2, 3)
            for component in source["tax_components"]:
                tax = half_up(Fraction(amount) * Fraction(component["rate"]))
                prefix += tax
                converted = translated(prefix, rate, 2, 3)
                assert component["foreign_tax_minor"] == tax and component["functional_tax_minor"] == converted - functional_prefix
                functional_prefix = converted
            assert source["foreign_gross_minor"] == prefix and source["functional_gross_minor"] == functional_prefix


@pytest.mark.parametrize("rate", [0, 1.1, True, "0", "-1", "NaN", "Infinity", "1e2", "01.2", "1.1234567890123"])
def test_untrusted_exchange_rates_are_rejected(rate: object) -> None:
    with pytest.raises(FinancePostingError):
        invoice_equation(replace(invoice(), original_rate=HistoricalRate(rate, "Synthetic", "2026-10-10T00:00:00Z")), "USD", CurrencyRegistryContext.from_installed())  # type: ignore[arg-type]


@pytest.mark.parametrize("change", [{"country_code":"US"}, {"transaction_class":"Goods"}, {"effective_from":"2026-10-11"}, {"effective_to":"2026-10-09"}, {"rate":"1.01"}])
def test_tax_policy_requires_exact_effective_country_date_and_transaction_class(change: dict[str, str]) -> None:
    request = invoice()
    with pytest.raises(FinancePostingError):
        invoice_equation(replace(request, taxes=(replace(request.taxes[0], **change),)), "USD", CurrencyRegistryContext.from_installed())


def test_original_currency_context_survives_global_policy_rebinding() -> None:
    CurrencyRegistry.reset_to_bundled()
    context = CurrencyRegistryContext.from_installed()
    request = invoice()
    before = invoice_equation(request, "USD", context)
    try:
        CurrencyRegistry.register(CurrencySpec("USD", "Synthetic drift", 3), registry_version="synthetic-fx-v2", source="Synthetic")
        assert invoice_equation(request, "USD", context) == before
        assert invoice_equation(request, "USD", CurrencyRegistryContext.from_installed())["functional_policy"] != before["functional_policy"]
    finally:
        CurrencyRegistry.reset_to_bundled()


@pytest.mark.parametrize(("paid", "historical", "amount", "day"), [(1, 0, 100, "2026-10-11"), (0, 0, 20000, "2026-10-11"), (0, 0, 100, "2026-10-09")])
def test_settlement_rejects_forged_historical_basis_overallocation_and_regressing_date(paid: int, historical: int, amount: int, day: str) -> None:
    context = CurrencyRegistryContext.from_installed()
    with pytest.raises(FinancePostingError):
        settlement_equation(invoice_equation(invoice(), "USD", context), foreign_minor=amount, foreign_before_minor=paid,
            historical_before_minor=historical, settlement_rate=HistoricalRate("1.2", "Synthetic", day+"T00:00:00Z"), posting_date=day, context=context)
