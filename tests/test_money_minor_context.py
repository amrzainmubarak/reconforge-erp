"""Minor-unit conversions must preserve the integer oracle under caller contexts."""

from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.db import connect, run_migrations
from reconforge.infrastructure import postgres_finance_core, sqlite_finance_core
from reconforge.platform import PlatformError
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.utils.money import CurrencyRegistry, CurrencyRegistryContext, InvalidAmountError, Money
from tests.test_finance_core import _seed_finance_model


def _amount_text(minor: int, precision: int) -> str:
    digits = str(abs(minor)).zfill(precision + 1)
    magnitude = digits if precision == 0 else digits[:-precision] + "." + digits[-precision:]
    return ("-" if minor < 0 else "") + magnitude


@pytest.mark.parametrize("currency,precision", [("JPY", 0), ("USD", 2), ("KWD", 3), ("CLF", 4)])
@pytest.mark.parametrize("minor", [0, 123456789, -123456789, 10**80 + 12345])
def test_money_minor_round_trip_ignores_low_precision_and_rounding(currency: str, precision: int, minor: int) -> None:
    expected = _amount_text(minor, precision)
    original = Money.from_exact(expected, currency, strict_precision=True)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert original.to_minor_units() == minor
        restored = Money.from_minor_units(minor, currency)
        assert str(restored.amount) == expected
        assert restored.to_minor_units() == minor
        assert restored.to_canonical_dict() == original.to_canonical_dict()


@given(minor=st.integers(min_value=-(10**80), max_value=10**80), precision=st.integers(1, 28))
def test_usd_minor_round_trip_is_exact_even_when_rounding_traps_are_enabled(minor: int, precision: int) -> None:
    expected = _amount_text(minor, 2)
    money = Money.from_exact(expected, "USD", strict_precision=True)
    with localcontext() as context:
        context.prec = precision
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert money.to_minor_units() == minor
        assert str(Money.from_minor_units(minor, "USD").amount) == expected


@pytest.mark.parametrize("invalid", [True, False, "1", Decimal("1"), 1.0])
def test_money_from_minor_rejects_non_integer_boundary_types(invalid: object) -> None:
    with pytest.raises(InvalidAmountError, match="minor_units must be an integer"):
        Money.from_minor_units(invalid, "USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("adapter", [sqlite_finance_core, postgres_finance_core])
def test_finance_adapter_preserves_exact_input_and_recorded_scale_under_low_precision(adapter: ModuleType) -> None:
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert adapter._amount_to_minor("1234567.89", "USD", "Debit") == 123456789
        assert adapter._minor_to_text(123456789, 2) == "1234567.89"
        assert adapter._minor_to_text(-123456789, 3) == "-123456.789"
        # Recorded precision stays authoritative independently of the current USD registry.
        assert adapter._minor_to_text(123456789, 4) == "12345.6789"
        with pytest.raises(PlatformError, match="exceeds the supported"):
            adapter._amount_to_minor("90000000000000000.01", "USD", "Debit")


def test_eight_digit_currency_policy_uses_exact_minor_conversion_and_retains_lineage() -> None:
    snapshot = CurrencyRegistry.snapshot()
    snapshot.pop("digest")
    snapshot["registry_version"] = "synthetic-eight-digit-policy-v1"
    for spec in snapshot["currencies"]:
        if spec["code"] == "USD":
            spec["minor_units"] = 8
    registry_context = CurrencyRegistryContext.from_snapshot(snapshot)
    with localcontext() as context:
        context.prec = 3
        value = Money.from_minor_units(123456789, "USD", registry_context=registry_context)
        assert value.to_minor_units() == 123456789
        assert str(value.amount) == "1.23456789"
        assert value.currency_registry_digest == registry_context.registry_manifest.digest


def test_sqlite_finance_saved_entry_readback_preserves_exact_amount_after_reconnect(tmp_path: Path) -> None:
    database = tmp_path / "hostile-context-finance.db"
    run_migrations(database)
    with connect(database, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            draft = finance.create_entry(
                entry_number="JE/EXACT/1", organization_code="SYN", entity_code="EG01",
                period_id=str(period["id"]), journal_code="GJ", posting_date="2026-07-05",
                description="Synthetic context-independent conversion", actor_label="maker",
                lines=[
                    {"account_code": "1010", "debit": "1234567.89", "dimensions": {"CC": "HQ"}},
                    {"account_code": "3000", "credit": "1234567.89", "dimensions": {"CC": "HQ"}},
                ],
            )
            assert draft["total_debit_minor"] == draft["total_credit_minor"] == 123456789
            assert draft["total_debit"] == draft["total_credit"] == "1234567.89"
            finance.validate_entry(str(draft["id"]), reason="Independent synthetic review", actor_label="checker")
            stored = connection.execute("SELECT SUM(debit_minor) FROM ledger_lines WHERE entry_id=?", (draft["id"],)).fetchone()
            assert stored[0] == 123456789
    with connect(database, require_exists=True) as connection, localcontext() as context:
        context.prec = 3
        detail = FinanceCoreService(connection).get_entry(str(draft["id"]))
        assert detail["status"] == "Validated"
        assert detail["total_debit"] == detail["total_credit"] == "1234567.89"
