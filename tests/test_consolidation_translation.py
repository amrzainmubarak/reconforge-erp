from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.application.consolidation import ConsolidationApplicationService
from reconforge.domain.consolidation import (
    ConsolidationBalance,
    ConsolidationError,
    ConsolidationPolicy,
    ConsolidationRate,
    ConsolidationRequest,
    translate_consolidation,
    verify_consolidation_result_payload,
)
from reconforge.infrastructure.object_consolidation import ObjectStoreConsolidationResultRepository
from reconforge.infrastructure.object_storage import LocalObjectStorageSettings, LocalObjectStore
from reconforge.utils.money import Money


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _balance(
    line_id: str,
    entity: str,
    source_account: str,
    group_account: str,
    account_type: str,
    amount: str,
    currency: str,
    rate_type: str,
    rate_bucket: str | None = None,
) -> ConsolidationBalance:
    return ConsolidationBalance(
        source_line_id=line_id,
        source_trial_balance_digest=_digest(f"trial-balance:{entity}"),
        entity_code=entity,
        source_account_code=source_account,
        group_account_code=group_account,
        account_type=account_type,
        period_id="2026-08",
        amount=Decimal(amount),
        currency=currency,
        rate_type=rate_type,
        rate_bucket=rate_bucket or f"{entity}-{rate_type}",
    )


def _balances() -> tuple[ConsolidationBalance, ...]:
    return (
        _balance("P-CASH", "PARENT", "1100", "1000", "Asset", "50.00", "USD", "closing"),
        _balance("P-EQUITY", "PARENT", "3100", "3000", "Equity", "-50.00", "USD", "historical"),
        _balance("S-CASH", "SUB-EU", "1200", "1000", "Asset", "100.00", "EUR", "closing"),
        _balance("S-EQUITY", "SUB-EU", "3200", "3000", "Equity", "-70.00", "EUR", "historical"),
        _balance("S-REVENUE", "SUB-EU", "4100", "4000", "Income", "-30.00", "EUR", "average"),
    )


def _rate(
    rate_id: str,
    rate_type: str,
    value: str,
    *,
    base_currency: str = "EUR",
    rate_bucket: str | None = None,
) -> ConsolidationRate:
    return ConsolidationRate(
        rate_id=rate_id,
        period_id="2026-08",
        rate_type=rate_type,
        base_currency=base_currency,
        reporting_currency="USD",
        rate=Decimal(value),
        source="Synthetic approved rate table",
        source_digest=_digest("approved-rate-table:2026-08"),
        effective_at="2026-08-31T23:59:59+02:00",
        rate_bucket=rate_bucket or f"SUB-EU-{rate_type}",
    )


def _rates() -> tuple[ConsolidationRate, ...]:
    return (
        _rate("EUR-USD-CLOSE", "closing", "1.20"),
        _rate("EUR-USD-HIST", "historical", "1.00"),
        _rate("EUR-USD-AVG", "average", "1.10"),
    )


def _request(
    *,
    balances: tuple[ConsolidationBalance, ...] | None = None,
    rates: tuple[ConsolidationRate, ...] | None = None,
) -> ConsolidationRequest:
    return ConsolidationRequest(
        group_code="GLOBAL-GROUP",
        period_id="2026-08",
        reporting_currency="USD",
        actor_id="controller-a",
        calculated_at="2026-08-01T10:00:00+02:00",
        policy=ConsolidationPolicy(
            policy_id="group-translation-policy",
            version="1.0.0",
            translation_adjustment_account_code="CTA-999",
            translation_adjustment_account_type="Equity",
        ),
        balances=_balances() if balances is None else balances,
        rates=_rates() if rates is None else rates,
    )


def _payload_digest(payload: dict[str, object]) -> str:
    material = {key: value for key, value in payload.items() if key != "result_digest"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def test_consolidation_translation_is_balanced_explainable_and_not_posted() -> None:
    result = translate_consolidation(_request())

    assert result.schema_version == 1
    assert result.algorithm_version == "consolidation-translation-v1"
    assert result.calculated_at == "2026-08-01T08:00:00Z"
    assert result.pre_adjustment_balance == Money.from_exact("17.00", "USD", strict_precision=True)
    assert result.translation_adjustment.amount == Money.from_exact("-17.00", "USD", strict_precision=True)
    assert result.translation_adjustment.required is True
    assert result.translation_adjustment.posted is False
    assert result.translation_adjustment.account_code == "CTA-999"
    assert result.post_adjustment_balance == Money.from_exact("0.00", "USD", strict_precision=True)
    assert result.unrounded_translation_difference == Decimal("17.0000")
    assert result.rounding_delta == Decimal("0.0000")
    assert [record.group_account_code for record in result.account_totals] == ["1000", "3000", "4000"]
    assert [record.amount.amount for record in result.account_totals] == [
        Decimal("170.00"),
        Decimal("-120.00"),
        Decimal("-33.00"),
    ]

    subsidiary_cash = next(record for record in result.lines if record.source_line_id == "S-CASH")
    assert subsidiary_cash.original_amount == Money.from_exact("100.00", "EUR", strict_precision=True)
    assert subsidiary_cash.translated_amount == Money.from_exact("120.00", "USD", strict_precision=True)
    assert subsidiary_cash.unrounded_translated_amount == Decimal("120.0000")
    assert subsidiary_cash.rate_id == "EUR-USD-CLOSE"
    assert subsidiary_cash.rate_bucket == "SUB-EU-closing"
    assert subsidiary_cash.rate_source == "Synthetic approved rate table"
    assert subsidiary_cash.rate_source_digest == _digest("approved-rate-table:2026-08")
    assert subsidiary_cash.rate_effective_at == "2026-08-31T21:59:59Z"
    assert subsidiary_cash.selection_reason == "exact-period-currency-rate-type-v1"

    parent_cash = next(record for record in result.lines if record.source_line_id == "P-CASH")
    assert parent_cash.rate_id == "IDENTITY-USD"
    assert parent_cash.rate == Decimal("1")
    assert parent_cash.selection_reason == "same-currency-identity-v1"


def test_row_and_rate_permutations_produce_identical_result_and_digests() -> None:
    first = translate_consolidation(_request())
    permuted = translate_consolidation(
        _request(balances=tuple(reversed(_balances())), rates=tuple(reversed(_rates())))
    )

    assert permuted.request_digest == first.request_digest
    assert permuted.result_digest == first.result_digest
    assert permuted.run_id == first.run_id
    assert permuted.to_dict() == first.to_dict()


@given(
    balance_order=st.permutations(_balances()),
    rate_order=st.permutations(_rates()),
)
@settings(max_examples=50, deadline=None)
def test_consolidation_is_property_invariant_under_input_permutations(
    balance_order: list[ConsolidationBalance],
    rate_order: list[ConsolidationRate],
) -> None:
    baseline = translate_consolidation(_request())
    candidate = translate_consolidation(
        _request(balances=tuple(balance_order), rates=tuple(rate_order))
    )

    assert candidate.to_dict() == baseline.to_dict()


def test_currency_specific_rounding_exposes_delta_and_cta() -> None:
    balances = (
        _balance("P-CASH", "PARENT", "1100", "1000", "Asset", "10.00", "USD", "closing"),
        _balance("P-EQUITY", "PARENT", "3100", "3000", "Equity", "-10.00", "USD", "historical"),
        _balance("J-CASH", "SUB-JP", "1200", "1000", "Asset", "101", "JPY", "closing"),
        _balance("J-EQUITY", "SUB-JP", "3200", "3000", "Equity", "-101", "JPY", "historical"),
    )
    rates = (
        _rate(
            "JPY-USD-CLOSE",
            "closing",
            "0.0067",
            base_currency="JPY",
            rate_bucket="SUB-JP-closing",
        ),
        _rate(
            "JPY-USD-HIST",
            "historical",
            "0.0064",
            base_currency="JPY",
            rate_bucket="SUB-JP-historical",
        ),
    )

    result = translate_consolidation(_request(balances=balances, rates=rates))

    assert result.pre_adjustment_balance.amount == Decimal("0.03")
    assert result.translation_adjustment.amount.amount == Decimal("-0.03")
    assert result.unrounded_translation_difference == Decimal("0.0303")
    assert result.rounding_delta == Decimal("-0.0003")
    assert result.post_adjustment_balance.amount == Decimal("0.00")


def test_explicit_rate_buckets_support_distinct_historical_rates_in_one_currency() -> None:
    balances = (
        _balance("P-CASH", "PARENT", "1100", "1000", "Asset", "10.00", "USD", "closing"),
        _balance("P-EQUITY", "PARENT", "3100", "3000", "Equity", "-10.00", "USD", "historical"),
        _balance("S-CASH", "SUB-EU", "1200", "1000", "Asset", "100.00", "EUR", "closing"),
        _balance(
            "S-EQUITY-A",
            "SUB-EU",
            "3200-A",
            "3000",
            "Equity",
            "-40.00",
            "EUR",
            "historical",
            "SUB-EU-HIST-A",
        ),
        _balance(
            "S-EQUITY-B",
            "SUB-EU",
            "3200-B",
            "3000",
            "Equity",
            "-30.00",
            "EUR",
            "historical",
            "SUB-EU-HIST-B",
        ),
        _balance("S-REVENUE", "SUB-EU", "4100", "4000", "Income", "-30.00", "EUR", "average"),
    )
    rates = (
        _rate("EUR-USD-CLOSE", "closing", "1.20"),
        _rate("EUR-USD-HIST-A", "historical", "1.00", rate_bucket="SUB-EU-HIST-A"),
        _rate("EUR-USD-HIST-B", "historical", "0.90", rate_bucket="SUB-EU-HIST-B"),
        _rate("EUR-USD-AVG", "average", "1.10"),
    )

    result = translate_consolidation(_request(balances=balances, rates=rates))

    assert result.pre_adjustment_balance.amount == Decimal("20.00")
    assert result.translation_adjustment.amount.amount == Decimal("-20.00")
    assert {
        record.source_line_id: record.rate_id
        for record in result.lines
        if record.source_line_id.startswith("S-EQUITY")
    } == {
        "S-EQUITY-A": "EUR-USD-HIST-A",
        "S-EQUITY-B": "EUR-USD-HIST-B",
    }


def test_financial_inputs_and_timezones_fail_closed() -> None:
    with pytest.raises(ConsolidationError, match="finite Decimal"):
        replace(_balances()[0], amount=10.0)
    with pytest.raises(ConsolidationError, match="finite Decimal"):
        replace(_rates()[0], rate=1.2)
    with pytest.raises(ConsolidationError, match="timezone-aware"):
        replace(_rates()[0], effective_at="2026-08-31T23:59:59")
    with pytest.raises(ConsolidationError, match="whole-second"):
        replace(_rates()[0], effective_at="2026-08-31T23:59:59.123+02:00")
    with pytest.raises(ConsolidationError, match="currency precision"):
        replace(_balances()[0], amount=Decimal("10.001"))


def test_request_rejects_unbalanced_mixed_or_ambiguous_sources() -> None:
    unbalanced = _balances()[:-1]
    with pytest.raises(ConsolidationError, match="source trial balance is not balanced"):
        _request(balances=unbalanced)

    mixed_currency = tuple(
        replace(record, currency="GBP") if record.source_line_id == "P-CASH" else record
        for record in _balances()
    )
    with pytest.raises(ConsolidationError, match="one functional currency"):
        _request(balances=mixed_currency)

    duplicate_line = _balances() + (replace(_balances()[0]),)
    with pytest.raises(ConsolidationError, match="source line identities must be unique"):
        _request(balances=duplicate_line)

    duplicate_rate_key = _rates() + (replace(_rates()[0], rate_id="EUR-USD-CLOSE-2"),)
    with pytest.raises(ConsolidationError, match="rate keys must be unique"):
        _request(rates=duplicate_rate_key)


def test_request_rejects_missing_unused_period_and_mapping_policy() -> None:
    with pytest.raises(ConsolidationError, match="required translation rate is missing"):
        _request(rates=_rates()[1:])

    unused = _rates() + (
        replace(
            _rates()[0],
            rate_id="GBP-USD-CLOSE",
            base_currency="GBP",
            source_digest=_digest("unused-gbp-rate"),
        ),
    )
    with pytest.raises(ConsolidationError, match="translation rate is unused"):
        _request(rates=unused)

    wrong_period = tuple(
        replace(record, period_id="2026-07") if record.source_line_id == "S-CASH" else record
        for record in _balances()
    )
    with pytest.raises(ConsolidationError, match="period does not match"):
        _request(balances=wrong_period)

    inconsistent_group_policy = tuple(
        replace(record, account_type="Expense") if record.source_line_id == "S-CASH" else record
        for record in _balances()
    )
    with pytest.raises(ConsolidationError, match="group-account translation policy is inconsistent"):
        _request(balances=inconsistent_group_policy)


def test_result_payload_schema_and_replay_verifier_reject_rehashed_tampering() -> None:
    result = translate_consolidation(_request())
    payload = result.to_dict()
    schema = json.loads(
        (Path(__file__).parents[1] / "docs" / "schemas" / "consolidation-translation-result-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.validate(payload, schema)
    verified = verify_consolidation_result_payload(payload)
    assert verified.result_digest == result.result_digest

    tampered = json.loads(json.dumps(payload))
    tampered["lines"][0]["translated_amount"]["amount"] = "999.00"
    tampered["result_digest"] = _payload_digest(tampered)
    with pytest.raises(ConsolidationError, match="does not reproduce"):
        verify_consolidation_result_payload(tampered)


def test_object_store_repository_is_immutable_idempotent_and_scope_isolated(tmp_path: Path) -> None:
    store = LocalObjectStore(LocalObjectStorageSettings(root=(tmp_path / "objects").resolve()))
    repository = ObjectStoreConsolidationResultRepository(store)
    service = ConsolidationApplicationService(repository)

    first = service.calculate_and_store(
        _request(), tenant_id="tenant-a", workspace_id="finance"
    )
    repeated = service.calculate_and_store(
        _request(), tenant_id="tenant-a", workspace_id="finance"
    )
    isolated = service.calculate_and_store(
        _request(), tenant_id="tenant-b", workspace_id="finance"
    )

    assert repeated.receipt == first.receipt
    assert isolated.receipt.object_key != first.receipt.object_key
    assert first.receipt.result_digest == first.result.result_digest
    assert first.receipt.sha256 == hashlib.sha256(first.receipt.content).hexdigest()
    loaded = service.load_and_verify(
        first.result.run_id,
        tenant_id="tenant-a",
        workspace_id="finance",
    )
    assert loaded.to_dict() == first.result.to_dict()
    with pytest.raises(ConsolidationError, match="artifact is unavailable"):
        service.load_and_verify(
            first.result.run_id,
            tenant_id="tenant-c",
            workspace_id="finance",
        )


def test_consolidation_application_boundary_has_no_infrastructure_or_database_import() -> None:
    source = Path("reconforge/application/consolidation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)


def test_consolidation_contract_and_decision_are_in_source_distribution_manifest() -> None:
    entries = set(Path("MANIFEST.in").read_text(encoding="utf-8").splitlines())

    assert {
        "include docs/adr/0210-consolidation-translation-is-balanced-explicit-and-non-posting.md",
        "include docs/consolidation-translation.md",
        "include docs/schemas/consolidation-translation-result-v1.schema.json",
    } <= entries
