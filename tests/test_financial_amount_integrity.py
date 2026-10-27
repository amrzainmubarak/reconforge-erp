from decimal import Decimal, localcontext

import pytest

from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    InvalidAmountError,
    parse_amount,
    parse_exact_amount,
    parse_guarded_amount_v3,
)


@pytest.mark.parametrize(
    "value", ["1,2", "12,34.56", "1,234.5,6", ",123", "123,", "1,,234", "1_234", "( -123.45 )", "(+123.45)"]
)
def test_malformed_default_amount_is_rejected(value: str) -> None:
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3(value)


@pytest.mark.parametrize("value", ["1.23.4,56", "1.234,5.6", "1.23,45", "1..234,00"])
def test_malformed_locale_amount_is_rejected(value: str) -> None:
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3(value, decimal_separator=",", thousands_separator=".")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1,234.56", "1234.56"), ("12,345,678.90", "12345678.90"), ("(1,234.56)", "-1234.56"), ("-1,234.56", "-1234.56")],
)
def test_conventional_formats_remain_supported(value: str, expected: str) -> None:
    assert parse_guarded_amount_v3(value) == Decimal(expected)


def test_locale_formats_remain_supported() -> None:
    assert parse_guarded_amount_v3("1.234,56", decimal_separator=",", thousands_separator=".") == Decimal("1234.56")
    assert parse_guarded_amount_v3("١٬٢٣٤٫٥٦", decimal_separator="٫", thousands_separator="٬") == Decimal("1234.56")
    assert parse_guarded_amount_v3(Decimal("1.234"), decimal_separator=",", thousands_separator=".") == Decimal("1.234")
    assert parse_guarded_amount_v3("1.234", decimal_separator=",", thousands_separator=".") == Decimal("1234")


def test_accounting_parentheses_preserve_exact_digits_in_hostile_context() -> None:
    with localcontext() as context:
        context.prec = 3
        context.rounding = "ROUND_DOWN"
        assert parse_guarded_amount_v3("(123456789.25)") == Decimal("-123456789.25")


def test_legacy_reader_retains_historical_grouping_semantics() -> None:
    assert parse_amount("1,2", input_policy=LEGACY_FINANCIAL_INPUT_POLICY) == Decimal("12")


def test_existing_v2_replay_semantics_are_preserved() -> None:
    assert parse_exact_amount("1,2") == Decimal("12")
    with localcontext() as context:
        context.prec = 3
        context.rounding = "ROUND_DOWN"
        assert parse_exact_amount("(123456789.25)") == Decimal("-1.23E+8")


def test_guarded_rejects_binary_floats() -> None:
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3(1.25)


def test_guarded_refuses_untrusted_objects_with_mutable_string_conversion() -> None:
    class ChangingValue:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            return "123" if self.calls == 1 else "1,23"

    value = ChangingValue()
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3(value)
    assert value.calls == 0

    class ChangingText(str):
        def __str__(self) -> str:
            return "1,23"

    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3(ChangingText("123"))


@pytest.mark.parametrize("separator", ["1", "e", "+", "-", "("])
def test_guarded_rejects_ambiguous_configured_separators(separator: str) -> None:
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3("123", decimal_separator=separator)


def test_typed_number_does_not_bypass_separator_validation() -> None:
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3(Decimal("1.234"), thousands_separator=".")


def test_unconfigured_decimal_separator_is_not_interpreted() -> None:
    with pytest.raises(InvalidAmountError):
        parse_guarded_amount_v3("1.25", decimal_separator=",")
