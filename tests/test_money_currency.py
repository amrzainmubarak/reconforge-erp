"""Tests for canonical Money, CurrencyRegistry, MinorMoney, Quantity, and ExchangeRate types."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.utils.money import (
    CurrencyMismatchError,
    CurrencyPolicyMismatchError,
    CurrencyRegistry,
    CurrencyRegistryContext,
    CurrencyRegistryContextMismatchError,
    CurrencySpec,
    ExchangeRate,
    InvalidAmountError,
    MinorMoney,
    Money,
    Quantity,
    UnknownCurrencyError,
)


@pytest.fixture(autouse=True)
def bundled_currency_registry() -> None:
    """Keep mutable registry tests isolated and deterministic."""

    CurrencyRegistry.reset_to_bundled()
    yield
    CurrencyRegistry.reset_to_bundled()


def test_currency_registry_defaults_and_custom_registration() -> None:
    usd = CurrencyRegistry.get("usd")
    assert usd.code == "USD"
    assert usd.minor_units == 2

    jpy = CurrencyRegistry.get("JPY")
    assert jpy.minor_units == 0

    kwd = CurrencyRegistry.get("KWD")
    assert kwd.minor_units == 3

    clf = CurrencyRegistry.get("CLF")
    assert clf.minor_units == 4

    CurrencyRegistry.register(CurrencySpec(code="BTC", name="Bitcoin", minor_units=8, symbol="₿"))
    btc = CurrencyRegistry.get("btc")
    assert btc.code == "BTC"
    assert btc.minor_units == 8

    with pytest.raises(InvalidAmountError, match="currency code cannot be empty"):
        CurrencyRegistry.get("   ")


def test_bundled_currency_registry_is_versioned_and_verifiable() -> None:
    manifest = CurrencyRegistry.manifest()
    snapshot = CurrencyRegistry.snapshot()

    assert manifest.schema_version == 1
    assert manifest.registry_version == "iso-4217-list-one-2026-01-01-rf1"
    assert manifest.published_at == "2026-01-01"
    assert manifest.currency_count >= 160
    assert len(manifest.digest) == 64
    assert snapshot["digest"] == manifest.digest
    assert snapshot["source_url"] == (
        "https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml"
    )
    assert CurrencyRegistry.install_snapshot(snapshot) == manifest


def test_currency_registry_file_and_canonical_snapshot_match_published_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs" / "schemas" / "currency_registry.schema.json").read_text(encoding="utf-8"))
    bundled = json.loads(
        (root / "reconforge" / "data" / "currency_registry.v1.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    validator.validate(bundled)
    validator.validate(CurrencyRegistry.snapshot())


def test_unknown_currency_fails_closed_across_canonical_types() -> None:
    with pytest.raises(UnknownCurrencyError, match="not registered: ZZZ"):
        CurrencyRegistry.get("ZZZ")
    with pytest.raises(UnknownCurrencyError, match="not registered: ZZZ"):
        Money("1.00", "ZZZ")
    with pytest.raises(UnknownCurrencyError, match="not registered: ZZZ"):
        MinorMoney(100, "ZZZ")
    with pytest.raises(UnknownCurrencyError, match="not registered: ZZZ"):
        ExchangeRate(base_currency="USD", quote_currency="ZZZ", rate=Decimal("1"))


def test_registry_file_update_is_atomic_and_does_not_require_core_code_change(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "registry_version": "customer-registry-2026-07-24",
        "published_at": "2026-07-24",
        "source": "Synthetic test registry",
        "source_url": "",
        "default_rounding_policy": "ROUND_HALF_UP",
        "currencies": [
            {"code": "USD", "name": "US Dollar", "minor_units": 2, "numeric_code": "840"},
            {"code": "BTC", "name": "Bitcoin test policy", "minor_units": 8},
        ],
    }
    registry_file = tmp_path / "currency-registry.json"
    registry_file.write_text(json.dumps(payload), encoding="utf-8")

    manifest = CurrencyRegistry.load_file(registry_file)

    assert manifest.registry_version == "customer-registry-2026-07-24"
    assert manifest.currency_count == 2
    assert CurrencyRegistry.get("BTC").minor_units == 8
    with pytest.raises(UnknownCurrencyError, match="not registered: EUR"):
        CurrencyRegistry.get("EUR")

    CurrencyRegistry.reset_to_bundled()
    assert CurrencyRegistry.load_file(registry_file, expected_digest=manifest.digest) == manifest
    before_wrong_expected_digest = CurrencyRegistry.manifest()
    with pytest.raises(InvalidAmountError, match="approved expected digest"):
        CurrencyRegistry.load_file(registry_file, expected_digest="f" * 64)
    assert CurrencyRegistry.manifest() == before_wrong_expected_digest

    before_failed_update = CurrencyRegistry.manifest()
    tampered = CurrencyRegistry.snapshot()
    tampered["digest"] = "0" * 64
    with pytest.raises(InvalidAmountError, match="digest verification failed"):
        CurrencyRegistry.install_snapshot(tampered)
    assert CurrencyRegistry.manifest() == before_failed_update


def test_money_captures_policy_and_rejects_silent_policy_drift() -> None:
    original = Money("1.23", "USD")
    original_minor_units = original.to_minor_units()

    CurrencyRegistry.register(
        CurrencySpec(code="USD", name="US Dollar test policy", minor_units=3),
        registry_version="test-usd-policy-v2",
        source="Synthetic policy drift test",
    )
    changed = Money("1.230", "USD", strict_precision=True)

    assert original_minor_units == original.to_minor_units() == 123
    assert changed.to_minor_units() == 1230
    assert original.currency_policy_digest != changed.currency_policy_digest
    with pytest.raises(CurrencyPolicyMismatchError, match="different financial policies"):
        _ = original + changed


def test_currency_registry_context_freezes_one_operation_snapshot() -> None:
    context = CurrencyRegistry.context()
    original = Money("1.23", "USD", registry_context=context)

    CurrencyRegistry.register(
        CurrencySpec(code="USD", name="US Dollar context policy", minor_units=3),
        registry_version="context-usd-policy-v2",
        source="Synthetic context test",
    )
    current = Money("1.230", "USD", strict_precision=True)
    frozen = Money("1.23", "USD", registry_context=context)

    assert context.registry_manifest.registry_version != CurrencyRegistry.manifest().registry_version
    assert original.currency_registry_digest == frozen.currency_registry_digest == context.registry_manifest.digest
    assert original.minor_units == frozen.minor_units == 2
    assert current.minor_units == 3
    assert context.get_precision("USD") == 2

    minor = MinorMoney(123, "USD", registry_context=context).to_money()
    rate = ExchangeRate("USD", "EUR", Decimal("1"), registry_context=context)
    CurrencyRegistry.register(
        CurrencySpec(code="EUR", name="Euro context policy", minor_units=3),
        registry_version="context-eur-policy-v2",
        source="Synthetic context test",
    )
    converted = rate.convert(Money("1.23", "USD", registry_context=context))
    assert minor.minor_units == 2
    assert converted.currency == "EUR"
    assert converted.minor_units == context.get_precision("EUR") == 2


def test_currency_registry_context_validates_snapshot_and_canonical_lineage() -> None:
    snapshot = CurrencyRegistry.snapshot()
    context = CurrencyRegistryContext.from_snapshot(snapshot)
    canonical = Money("4.20", "USD", registry_context=context).to_canonical_dict()

    assert context.snapshot() == snapshot
    assert Money.from_canonical_dict(canonical, registry_context=context).to_canonical_dict() == canonical

    changed = dict(canonical)
    changed["currency_registry_version"] = "other-context-v1"
    with pytest.raises(CurrencyRegistryContextMismatchError, match="operation context"):
        Money.from_canonical_dict(changed, registry_context=context)

    tampered = dict(snapshot)
    tampered["digest"] = "0" * 64
    with pytest.raises(InvalidAmountError, match="digest verification failed"):
        CurrencyRegistryContext.from_snapshot(tampered)


def test_money_construction_and_invariants() -> None:
    m1 = Money("100.50", "USD")
    assert m1.amount == Decimal("100.50")
    assert m1.currency == "USD"
    assert m1.as_canonical_str() == "100.50 USD"

    # Currency precision rounding
    m_jpy = Money("100.75", "JPY")
    assert m_jpy.amount == Decimal("101")

    m_kwd = Money("100.1234", "KWD")
    assert m_kwd.amount == Decimal("100.123")

    # Strict precision validation
    with pytest.raises(InvalidAmountError, match="financial amount exceeds configured currency precision"):
        Money("100.1234", "USD", strict_precision=True)

    # Numeric value, not lexical trailing-zero scale, defines currency precision.
    assert Money("100.5000", "USD", strict_precision=True).amount == Decimal("100.50")

    # Rejection of invalid types and scientific notation
    with pytest.raises(InvalidAmountError, match="financial amount is missing or invalid"):
        Money(None, "USD")

    with pytest.raises(InvalidAmountError, match="financial amount is missing or invalid"):
        Money(True, "USD")

    with pytest.raises(InvalidAmountError, match="scientific notation"):
        Money("1.5e3", "USD")


def test_money_boundary_values_remain_exact() -> None:
    huge = f"{'9' * 500}.99"

    assert Money("0", "USD", strict_precision=True).amount == Decimal("0.00")
    assert Money("(1,234.50)", "USD", strict_precision=True).amount == Decimal("-1234.50")
    huge_money = Money(huge, "USD", strict_precision=True)
    assert huge_money.amount == Decimal(huge)
    assert (huge_money + Money("0.01", "USD")).amount == Decimal(f"1{'0' * 500}.00")
    assert (huge_money * 2).amount == Decimal(f"1{'9' * 500}.98")

    rounded_lines = [Money("0.005", "USD") for _ in range(3)]
    accumulated = rounded_lines[0] + rounded_lines[1] + rounded_lines[2]
    assert accumulated.amount == Decimal("0.03")


def test_money_arithmetic_and_currency_mismatch_enforcement() -> None:
    m1 = Money("100.50", "USD")
    m2 = Money("49.50", "USD")

    assert (m1 + m2) == Money("150.00", "USD")
    assert (m1 - m2) == Money("51.00", "USD")
    assert (m1 * 2) == Money("201.00", "USD")
    assert (2 * m1) == Money("201.00", "USD")
    assert (m1 / 2) == Money("50.25", "USD")

    with pytest.raises(InvalidAmountError, match="division by zero"):
        _ = m1 / 0

    m_eur = Money("100.50", "EUR")
    with pytest.raises(CurrencyMismatchError, match="Cannot perform financial operation between USD and EUR"):
        _ = m1 + m_eur

    with pytest.raises(CurrencyMismatchError, match="Cannot perform financial operation between USD and EUR"):
        _ = m1 - m_eur

    with pytest.raises(CurrencyMismatchError, match="Cannot perform financial operation between USD and EUR"):
        _ = m1 < m_eur


def test_money_minor_units_conversion() -> None:
    usd_money = Money("12.50", "USD")
    assert usd_money.to_minor_units() == 1250
    assert Money.from_minor_units(1250, "USD") == usd_money
    assert MinorMoney(1250, "USD").to_money() == usd_money

    kwd_money = Money("1.250", "KWD")
    assert kwd_money.to_minor_units() == 1250
    assert Money.from_minor_units(1250, "KWD") == kwd_money
    assert MinorMoney(1250, "KWD").to_money() == kwd_money

    jpy_money = Money("1500", "JPY")
    assert jpy_money.to_minor_units() == 1500
    assert Money.from_minor_units(1500, "JPY") == jpy_money
    assert Money.from_minor_units(1500, "JPY") == jpy_money


def test_money_serialization_and_dict_roundtrip() -> None:
    m = Money("250.75", "EUR")
    d = m.to_dict()
    assert d == {"amount": "250.75", "currency": "EUR"}
    restored = Money.from_dict(d)
    assert restored == m

    canonical = m.to_canonical_dict()
    assert canonical["minor_units"] == 2
    assert canonical["rounding_policy"] == "ROUND_HALF_UP"
    assert canonical["currency_registry_version"] == CurrencyRegistry.manifest().registry_version
    assert Money.from_canonical_dict(canonical).to_canonical_dict() == canonical

    tampered = dict(canonical)
    tampered["minor_units"] = 3
    with pytest.raises(CurrencyPolicyMismatchError, match="does not match the installed policy"):
        Money.from_canonical_dict(tampered)


def test_exchange_rate_conversion() -> None:
    rate = ExchangeRate(
        base_currency="USD",
        quote_currency="EUR",
        rate=Decimal("0.9200"),
        source="ECB",
        effective_at="2026-07-24T00:00:00Z",
    )
    usd = Money("100.00", "USD")
    eur = rate.convert(usd)
    assert eur == Money("92.00", "EUR")

    eur_money = Money("100.00", "EUR")
    with pytest.raises(CurrencyMismatchError, match="Exchange rate base currency \\(USD\\) does not match"):
        rate.convert(eur_money)


def test_quantity() -> None:
    q1 = Quantity(Decimal("100.5"), unit="KG")
    assert q1.value == Decimal("100.5")
    assert q1.unit == "KG"

    with pytest.raises(InvalidAmountError, match="unit cannot be empty"):
        Quantity(Decimal("10"), unit="   ")
