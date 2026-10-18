"""Original-rate inversion checked by independent integer/Fraction arithmetic."""

from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.utils.money import (
    CurrencyMismatchError,
    CurrencyPolicyMismatchError,
    CurrencyRegistry,
    CurrencyRegistryContext,
    ExchangeRate,
    InvalidAmountError,
    Money,
)


def oracle(minor: int, rate: str, source_precision: int, target_precision: int) -> int:
    magnitude = abs(Fraction(minor) / Fraction(rate) * Fraction(10) ** (target_precision - source_precision))
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    rounded = whole + (2 * remainder >= magnitude.denominator)
    return -rounded if minor < 0 else rounded


@pytest.mark.parametrize("base,quote,rate,minor", [
    ("USD", "EUR", "1.25", 12501), ("USD", "GBP", "0.82", 5741),
    ("JPY", "USD", "0.00625", 1), ("KWD", "JPY", "490.75", 101),
    ("CLF", "USD", "33.123456789012", 1999999999),
    ("USD", "EUR", "2", 1), ("USD", "EUR", "2", -1),
    ("USD", "EUR", "3", 1), ("USD", "EUR", "3", -1),
    ("USD", "EUR", "1.000000000001", 0),
])
def test_inverse_original_rate_matches_independent_minor_oracle(base: str, quote: str, rate: str, minor: int) -> None:
    original = ExchangeRate(base, quote, Decimal(rate), "SYNTHETIC", "2026-10-12T00:00:00Z")
    money = Money.from_minor_units(minor, quote)
    value = original.convert_inverse(money)
    assert value.currency == base
    assert value.to_minor_units() == oracle(minor, rate, money.minor_units, value.minor_units)
    assert (original.rate, original.source, original.effective_at) == (Decimal(rate), "SYNTHETIC", "2026-10-12T00:00:00Z")


@given(minor=st.integers(-(10**80), 10**80), coefficient=st.integers(1, 10**24 - 1), scale=st.integers(0, 12))
def test_inverse_ignores_ambient_decimal_context(minor: int, coefficient: int, scale: int) -> None:
    digits = tuple(int(value) for value in str(coefficient))
    rate = Decimal((0, digits, -scale))
    original = ExchangeRate("USD", "EUR", rate)
    money = Money.from_minor_units(minor, "EUR")
    with localcontext() as context:
        context.prec = 1
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = context.traps[Rounded] = True
        result = original.convert_inverse(money)
        assert result.to_minor_units() == oracle(minor, str(rate), 2, 2)
        assert context.prec == 1 and context.rounding == ROUND_DOWN
        assert context.traps[Inexact] and context.traps[Rounded]


def test_quote_policy_mismatch_is_refused_and_target_lineage_retained() -> None:
    snapshot = CurrencyRegistry.snapshot()
    snapshot.pop("digest")
    snapshot["registry_version"] = "synthetic-inverse-policy-v1"
    for spec in snapshot["currencies"]:
        if spec["code"] == "EUR":
            spec["minor_units"] = 3
    context = CurrencyRegistryContext.from_snapshot(snapshot)
    rate = ExchangeRate("USD", "EUR", Decimal("1.25"), registry_context=context)
    with pytest.raises(CurrencyPolicyMismatchError):
        rate.convert_inverse(Money.from_minor_units(1250, "EUR"))
    result = rate.convert_inverse(Money.from_minor_units(1250, "EUR", registry_context=context))
    assert result.to_minor_units() == 100
    assert result.currency_registry_digest == context.registry_manifest.digest


@pytest.mark.parametrize("invalid", [None, "1", 1, True, Decimal("1")])
def test_inverse_requires_canonical_money(invalid: object) -> None:
    with pytest.raises(InvalidAmountError, match="Money object"):
        ExchangeRate("USD", "EUR", Decimal("1.25")).convert_inverse(invalid)  # type: ignore[arg-type]


def test_inverse_currency_mismatch_and_quantization_loss_are_explicit() -> None:
    rate = ExchangeRate("USD", "EUR", Decimal("0.3"))
    with pytest.raises(CurrencyMismatchError, match="quote currency"):
        rate.convert_inverse(Money.from_minor_units(1, "USD"))
    original = Money.from_minor_units(1, "USD")
    assert rate.convert_inverse(rate.convert(original)).to_minor_units() == 0


def test_existing_money_division_intentional_rounding_survives_diagnostic_traps() -> None:
    value = Money.from_minor_units(100, "USD")
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = context.traps[Rounded] = True
        assert value.divide_exact("3").to_minor_units() == 33
        assert context.traps[Inexact] and context.traps[Rounded]


@pytest.mark.parametrize("rate,expected", [("999999999998.000000000001", 0), ("999999999997.999999999999", 1)])
@pytest.mark.parametrize("sign", [1, -1])
def test_original_rate_inverse_does_not_double_round_near_half(rate: str, expected: int, sign: int) -> None:
    original = ExchangeRate("USD", "EUR", Decimal(rate))
    value = Money.from_minor_units(sign * 499999999999, "EUR")
    assert original.convert_inverse(value).to_minor_units() == sign * expected
