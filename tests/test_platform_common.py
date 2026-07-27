from __future__ import annotations

import pytest

from reconforge.platform.common import PlatformError, parse_financial_amount, to_float, to_int


def test_to_float_rejects_invalid_amounts() -> None:
    for value in (None, "", "N/A", "nan", "1e2", "abc"):
        with pytest.raises(PlatformError):
            to_float(value)


def test_to_int_rejects_invalid_and_fractional_values() -> None:
    for value in (None, "", "N/A", "nan", "2.5", "1e3"):
        with pytest.raises(PlatformError):
            to_int(value)


def test_to_float_default_is_explicit_and_not_silent_zero() -> None:
    assert to_float("bad-value", default=10.5) == 10.5


def test_to_int_default_is_explicit_and_not_silent_zero() -> None:
    assert to_int("bad-value", default=7) == 7


def test_to_float_parses_numeric_inputs() -> None:
    assert to_float("1,250.50") == 1250.5
    assert to_float("(1,250.50)") == -1250.5


def test_to_int_parses_integer_inputs() -> None:
    assert to_int("1,250") == 1250
    assert to_int("-42") == -42


def test_parse_financial_amount_reports_field_context() -> None:
    with pytest.raises(PlatformError, match="Could not parse financial amount for field 'test field'"):
        parse_financial_amount("not-a-number", field="test field")


def test_parse_financial_amount_accepts_parenthesis_and_thousands() -> None:
    assert parse_financial_amount("(1,250.25)") == -(1250.25)
    assert parse_financial_amount("1,250.25") == 1250.25
