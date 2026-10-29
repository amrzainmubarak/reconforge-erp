"""Checks that hosted matching cannot replace authoritative source fields."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from typing import Any

import numpy as np
import pytest

import reconforge.workers.postgres_reconciliation as worker_module
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorkerError,
    ReconciliationExecutionContext,
    ReconciliationInputPartition,
    _stable_partition_key,
)


def _record(side: str, source_id: str, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "side": side,
        "source_id": source_id,
        "amount_decimal": Decimal("1.00"),
        "amount_original": "1.00",
        "currency_code": "USD",
        "date_value": "2026-10-28",
        "date_original": "2026-10-28",
        "reference_normalized": "REF",
        "reference_original": "REF",
        "valid": True,
        "attributes_json": {},
    }
    record.update(overrides)
    return record


def _run(left: dict[str, Any], right: dict[str, Any], rule: dict[str, Any] | None = None):
    adapter = LocalDeterministicMatcherAdapter()
    try:
        return adapter(ReconciliationExecutionContext(
            run={"rule_json": rule or {}}, left_inputs=(left,), right_inputs=(right,),
            heartbeat=lambda _: {}, cancellation_requested=lambda: False,
        ))
    finally:
        adapter.close()


@pytest.mark.parametrize("field,value", [
    ("id", "left-other"), ("source_id", "left-other"),
    ("amount", "999"), ("date", "2026-01-01"), ("reference", "OTHER"),
    ("currency", "EUR"), ("currency_code", "EUR"), ("ccy", "EUR"),
    ("amount_decimal", "999"), ("amount_original", "999"),
    ("date_value", "2026-01-01"), ("date_original", "2026-01-01"),
    ("reference_normalized", "OTHER"), ("reference_original", "OTHER"),
])
def test_hosted_record_rejects_shadowed_authoritative_source(field: str, value: str) -> None:
    left = _record("Left", "left-a", attributes_json={field: value})
    right = _record("Right", "right-a")
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, right)


@pytest.mark.parametrize("record_override,attribute", [
    ({"amount_decimal": None, "amount_original": ""}, {"amount": "1.00"}),
    ({"currency_code": ""}, {"currency": "USD"}),
    ({"date_value": None, "date_original": ""}, {"date": "2026-10-28"}),
    ({"reference_normalized": "", "reference_original": ""}, {"reference": "REF"}),
])
def test_missing_canonical_values_are_not_filled_by_untrusted_attributes(
    record_override: dict[str, Any], attribute: dict[str, str],
) -> None:
    left = _record("Left", "left-a", attributes_json=attribute, **record_override)
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, _record("Right", "right-a"))


@pytest.mark.parametrize("missing,attribute", [
    (("amount_decimal", "amount_original"), {"amount": "1.00"}),
    (("currency_code",), {"currency": "USD"}),
    (("date_value", "date_original"), {"date": "2026-10-28"}),
    (("reference_normalized", "reference_original"), {"reference": "REF"}),
])
def test_absent_canonical_keys_do_not_authorize_attributes(
    missing: tuple[str, ...], attribute: dict[str, str],
) -> None:
    record = _record("Left", "left-a", attributes_json=attribute)
    for key in missing:
        record.pop(key)
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(record, _record("Right", "right-a"))


@pytest.mark.parametrize("source_id", [None, "", "  ", " left-a ", "a\nb", "a" * 161, 0, True])
def test_missing_or_malformed_source_identity_never_generates_an_identity(source_id: object) -> None:
    left = _record("Left", "left-a")
    left["source_id"] = source_id
    right = _record("Right", "right-a")
    with pytest.raises(PostgresReconciliationWorkerError, match="identity"):
        _run(left, right)


def test_absent_source_identity_key_never_generates_an_identity() -> None:
    left = _record("Left", "left-a")
    left.pop("source_id")
    with pytest.raises(PostgresReconciliationWorkerError, match="identity"):
        _run(left, _record("Right", "right-a"))


@pytest.mark.parametrize("source_id", ["a\x00b", "a\tb", "a\rb", "a\x1fb", "a\x7fb", "a" * 255, "a" * 256])
def test_source_identity_rejects_control_characters_and_engine_truncation(source_id: str) -> None:
    left = _record("Left", "left-a")
    left["source_id"] = source_id
    with pytest.raises(PostgresReconciliationWorkerError, match="identity"):
        _run(left, _record("Right", "right-a"))


def test_source_identity_at_engine_limit_is_preserved() -> None:
    left = _record("Left", "a" * 160)
    outcome = _run(left, _record("Right", "right-a"))
    assert outcome.results[0]["left_id"] == "a" * 160


@pytest.mark.parametrize("value", [None, "false", "0", "True", 0, 1, 0.0, [], {}])
def test_nonboolean_valid_flag_is_never_coerced_to_valid(value: object) -> None:
    left = _record("Left", "left-a", valid=value)
    with pytest.raises(PostgresReconciliationWorkerError, match="valid"):
        _run(left, _record("Right", "right-a"))


def test_absent_valid_flag_is_unknown_not_inferred_true() -> None:
    left = _record("Left", "left-a")
    left.pop("valid")
    with pytest.raises(PostgresReconciliationWorkerError, match="valid"):
        _run(left, _record("Right", "right-a"))


def test_false_valid_flag_is_not_overridden_by_attributes() -> None:
    left = _record("Left", "left-a", valid=False, attributes_json={"valid": True})
    result = _run(left, _record("Right", "right-a"))
    assert not any(item["status"] == "Matched" for item in result.results)
    assert any(item["reason_code"] == "INVALID_RECORD" for item in result.exceptions)


class _UnformattableDecimal(Decimal):
    def __str__(self) -> str:
        raise AssertionError("oversized Decimal must not be stringified")

    def __format__(self, format_spec: str) -> str:
        raise AssertionError("oversized Decimal must not be formatted")


class _DeceptiveInt(int):
    def __str__(self) -> str:
        return "1"


class _DeceptiveStr(str):
    def __str__(self) -> str:
        return "1"


class _DeceptiveDecimal(Decimal):
    def __format__(self, format_spec: str) -> str:
        return "1"


@pytest.mark.parametrize("raw", [pytest.param("1" * 10000, id="integer"),
                                  pytest.param("0." + "1" * 10000, id="fraction")])
def test_oversized_decimal_is_rejected_before_string_formatting(raw: str) -> None:
    left = _record("Left", "left-a", amount_decimal=_UnformattableDecimal(raw), attributes_json={"amount": "1"})
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, _record("Right", "right-a"))


@pytest.mark.parametrize("raw", [pytest.param("1" * 10000, id="integer"),
                                  pytest.param("0." + "1" * 10000, id="fraction")])
def test_exact_decimal_coefficient_is_bounded_before_format(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    value = Decimal(raw)
    original_format = format

    def reject_large_format(candidate: object, spec: str) -> str:
        if candidate is value:
            raise AssertionError("oversized Decimal was formatted")
        return original_format(candidate, spec)

    monkeypatch.setattr(worker_module, "format", reject_large_format, raising=False)
    left = _record("Left", "left-a", amount_decimal=value, attributes_json={"amount": "1"})
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, _record("Right", "right-a"))


@pytest.mark.parametrize("value", [_DeceptiveInt(999), _DeceptiveStr("999"), _DeceptiveDecimal("999")])
def test_custom_numeric_subclasses_cannot_spoof_source_amount(value: object) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a", amount_decimal=value), _record("Right", "right-a"))


def test_custom_string_subclass_cannot_spoof_source_identity() -> None:
    left = _record("Left", "left-a")
    left["source_id"] = _DeceptiveStr("left-a")
    with pytest.raises(PostgresReconciliationWorkerError, match="identity"):
        _run(left, _record("Right", "right-a"))


@pytest.mark.parametrize("raw,source", [("12,3", "123"), ("1,23,456", "123456"), ("(12,3)", "-123")])
@pytest.mark.parametrize("policy", ["legacy-financial-input-v1", "strict-financial-input-v2"])
def test_malformed_grouping_is_refused_before_matching(raw: str, source: str, policy: str) -> None:
    left = _record("Left", "left-a", amount_decimal=Decimal(source), attributes_json={"amount": raw})
    right = _record("Right", "right-a", amount_decimal=Decimal(source))
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, right, {"financial_input_policy": policy})


def test_malformed_source_amount_is_rejected_even_without_attribute() -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a", amount_decimal="12,3"),
             _record("Right", "right-a", amount_decimal=Decimal("123")))


@pytest.mark.parametrize("policy", ["legacy-financial-input-v1", "strict-financial-input-v2"])
def test_valid_grouped_amount_still_matches(policy: str) -> None:
    left = _record("Left", "left-a", amount_decimal=Decimal("1234.56"), attributes_json={"amount": "1,234.56"})
    right = _record("Right", "right-a", amount_decimal=Decimal("1234.56"))
    result = _run(left, right, {"financial_input_policy": policy})
    assert result.results[0]["status"] == "Matched"


@pytest.mark.parametrize("value", [0.5, np.float32(0.5), np.float64(0.5), np.array(0.5)])
@pytest.mark.parametrize("policy", ["legacy-financial-input-v1", "strict-financial-input-v2"])
def test_binary_float_source_amount_is_rejected_before_matching(value: object, policy: str) -> None:
    left = _record("Left", "left-a", amount_decimal=value)
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, _record("Right", "right-a", amount_decimal=Decimal("0.5")), {"financial_input_policy": policy})


@pytest.mark.parametrize("policy", ["legacy-financial-input-v1", "strict-financial-input-v2"])
def test_binary_float_attribute_amount_is_rejected_before_matching(policy: str) -> None:
    left = _record("Left", "left-a", amount_decimal=Decimal("0.5"), attributes_json={"amount": 0.5})
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, _record("Right", "right-a", amount_decimal=Decimal("0.5")), {"financial_input_policy": policy})


@pytest.mark.parametrize("currency", [None, "", " ", " USD ", "usd", "ZZZ", 1, True])
def test_missing_unknown_or_noncanonical_currency_never_enters_matching(currency: object) -> None:
    left = _record("Left", "left-a", currency_code=currency)
    right = _record("Right", "right-a", currency_code=currency)
    with pytest.raises(PostgresReconciliationWorkerError, match="currency"):
        _run(left, right)


def test_absent_currency_key_never_enters_matching() -> None:
    left, right = _record("Left", "left-a"), _record("Right", "right-a")
    left.pop("currency_code")
    right.pop("currency_code")
    with pytest.raises(PostgresReconciliationWorkerError, match="currency"):
        _run(left, right)


@pytest.mark.parametrize("field", ["currency", "ccy", "department"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_exact_fields_require_nonempty_values_from_each_input(field: str, value: object) -> None:
    attrs = {field: value}
    with pytest.raises(PostgresReconciliationWorkerError, match="exact_fields|canonical"):
        _run(_record("Left", "left-a", attributes_json=attrs),
             _record("Right", "right-a", attributes_json=attrs), {"exact_fields": field})


@pytest.mark.parametrize("field", ["currency", "ccy", "department"])
def test_exact_fields_cannot_be_missing_from_both_inputs(field: str) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="exact_fields|canonical"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"), {"exact_fields": field})


def test_exact_field_currency_code_uses_existing_canonical_value() -> None:
    result = _run(_record("Left", "left-a"), _record("Right", "right-a"), {"exact_fields": "currency_code"})
    assert result.results[0]["status"] == "Matched"


@pytest.mark.parametrize("value", [[], {}, {"key": "value"}, ["A"], 0.5])
def test_exact_field_rejects_structured_or_binary_float_values(value: object) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="exact_fields"):
        _run(_record("Left", "left-a", attributes_json={"department": value}),
             _record("Right", "right-a", attributes_json={"department": value}),
             {"exact_fields": "department"})


@pytest.mark.parametrize("value", [0, False])
def test_exact_field_retains_present_zero_and_false(value: object) -> None:
    result = _run(_record("Left", "left-a", attributes_json={"department": value}),
                  _record("Right", "right-a", attributes_json={"department": value}),
                  {"exact_fields": "department"})
    assert result.results[0]["status"] == "Matched"


def test_custom_mapping_equal_to_source_keeps_match_and_identity() -> None:
    rule = {"amount_field": "invoice_total", "date_field": "business_day", "reference_field": "invoice_ref"}
    attrs = {"invoice_total": "1.0", "business_day": "2026-10-28", "invoice_ref": "REF", "currency": "USD"}
    outcome = _run(_record("Left", "left-a", attributes_json=attrs), _record("Right", "right-a"), rule)
    assert len(outcome.results) == 1
    assert outcome.results[0]["status"] == "Matched"
    assert outcome.results[0]["left_id"] == "left-a"


def test_custom_mapping_cannot_override_source_amount() -> None:
    rule = {"amount_field": "invoice_total"}
    left = _record("Left", "left-a", attributes_json={"invoice_total": "999"})
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(left, _record("Right", "right-a", amount_decimal=Decimal("999")), rule)


def test_original_amount_mapping_preserves_equal_source_and_refuses_conflicts() -> None:
    rule = {"amount_field": "amount_original"}
    left = _record("Left", "left-a", attributes_json={"amount_original": "1.00"})
    outcome = _run(left, _record("Right", "right-a"), rule)
    assert outcome.results[0]["status"] == "Matched"
    conflicting = _record("Left", "left-a", attributes_json={"amount_original": "999"})
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(conflicting, _record("Right", "right-a"), rule)


def test_overlapping_mapped_fields_are_rejected() -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"), {"amount_field": "id"})


@pytest.mark.parametrize("field,value,mapping", [
    ("amount", "0", {"amount_field": "invoice_total"}),
    ("date", "2026-01-01", {"date_field": "business_day"}),
    ("reference", "WRONG", {"reference_field": "invoice_ref"}),
])
@pytest.mark.parametrize("guard_use", ["exact_fields", "partition_fields"])
def test_default_alias_conflict_cannot_control_custom_exact_or_partition(
    field: str, value: str, mapping: dict[str, str], guard_use: str,
) -> None:
    rule: dict[str, Any] = {**mapping, guard_use: [field], "amount_tolerance": "1000"}
    left = _record("Left", "left-a", attributes_json={field: value})
    right = _record("Right", "right-a", amount_decimal=Decimal("999"), attributes_json={field: value})
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical|partition"):
        _run(left, right, rule)


@pytest.mark.parametrize("field,mapping", [
    ("amount", {"amount_field": "invoice_total"}),
    ("date", {"date_field": "business_day"}),
    ("reference", {"reference_field": "invoice_ref"}),
])
@pytest.mark.parametrize("guard_use", ["exact_fields", "partition_fields"])
def test_missing_default_alias_cannot_be_used_by_custom_exact_or_partition(
    field: str, mapping: dict[str, str], guard_use: str,
) -> None:
    rule: dict[str, Any] = {**mapping, guard_use: [field]}
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical|partition"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"), rule)


def test_present_matching_default_alias_works_with_custom_exact_field() -> None:
    rule = {"amount_field": "invoice_total", "exact_fields": ["amount"]}
    left = _record("Left", "left-a", attributes_json={"amount": "1.00"})
    right = _record("Right", "right-a", attributes_json={"amount": "1.00"})
    outcome = _run(left, right, rule)
    assert outcome.results[0]["status"] == "Matched"


def test_comma_separated_exact_field_inside_list_requires_missing_alias() -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"),
             {"amount_field": "invoice_total", "exact_fields": ["amount,department"]})


@pytest.mark.parametrize("exact_fields", ["amount", " amount, department "])
def test_string_exact_fields_require_missing_canonical_alias(exact_fields: str) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"),
             {"amount_field": "invoice_total", "exact_fields": exact_fields})


def test_string_exact_field_rejects_conflicting_canonical_alias() -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a", attributes_json={"amount": "0"}),
             _record("Right", "right-a"), {"amount_field": "invoice_total", "exact_fields": "amount"})


@pytest.mark.parametrize("exact_fields", [None, "", [], ["department"], ["department", "location"],
                                          "department", "department,location"])
def test_valid_exact_field_shapes_keep_existing_matching_semantics(exact_fields: object) -> None:
    attrs = {"department": "A", "location": "B"}
    outcome = _run(_record("Left", "left-a", attributes_json=attrs),
                   _record("Right", "right-a", attributes_json=attrs), {"exact_fields": exact_fields})
    assert outcome.results[0]["status"] == "Matched"


@pytest.mark.parametrize("exact_fields", [42, True, {"amount": "X"}, [None], [1], [["amount"]]])
def test_unsupported_exact_field_shapes_fail_closed(exact_fields: object) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="exact_fields"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"), {"exact_fields": exact_fields})


@pytest.mark.parametrize("mapping", [
    {"amount_field": "date"}, {"amount_field": "date_value"}, {"amount_field": "date_original"},
    {"amount_field": "reference"}, {"amount_field": "reference_normalized"},
    {"amount_field": "reference_original"},
    {"date_field": "amount"}, {"date_field": "amount_decimal"}, {"date_field": "amount_original"},
    {"date_field": "reference"}, {"date_field": "reference_normalized"},
    {"date_field": "reference_original"},
    {"reference_field": "amount"}, {"reference_field": "amount_decimal"},
    {"reference_field": "amount_original"}, {"reference_field": "date"},
    {"reference_field": "date_value"}, {"reference_field": "date_original"},
])
def test_canonical_field_names_cannot_be_reused_by_another_domain(mapping: dict[str, str]) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"), mapping)


@pytest.mark.parametrize("mapping,overrides", [
    ({"amount_field": "amount_decimal"}, {"amount_decimal": None, "amount_original": "1"}),
    ({"amount_field": "amount_original"}, {"amount_original": ""}),
    ({"date_field": "date_value"}, {"date_value": None}),
    ({"date_field": "date_original"}, {"date_original": ""}),
    ({"reference_field": "reference_normalized"}, {"reference_normalized": ""}),
    ({"reference_field": "reference_original"}, {"reference_original": ""}),
])
def test_explicit_canonical_mapping_cannot_fill_missing_alias_from_another_source(
    mapping: dict[str, str], overrides: dict[str, Any],
) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a", **overrides), _record("Right", "right-a"), mapping)


def test_streamed_partition_rejects_conflict_before_yield_but_earlier_output_remains() -> None:
    good = ReconciliationInputPartition(
        partition_key=_stable_partition_key(["A"]),
        left_inputs=(_record("Left", "left-a", attributes_json={"amount": "1", "department": "A"}),),
        right_inputs=(_record("Right", "right-a", attributes_json={"amount": "1", "department": "A"}),),
    )
    bad = ReconciliationInputPartition(
        partition_key=_stable_partition_key(["B"]),
        left_inputs=(_record("Left", "left-b", attributes_json={"amount": "0", "department": "B"}),),
        right_inputs=(_record("Right", "right-b", amount_decimal=Decimal("999"),
                              attributes_json={"amount": "0", "department": "B"}),),
    )
    context = ReconciliationExecutionContext(
        run={"rule_json": {"amount_field": "invoice_total", "partition_fields": ["department"],
                           "amount_tolerance": "1000"}}, left_inputs=(), right_inputs=(),
        heartbeat=lambda _: {}, cancellation_requested=lambda: False, partition_supplier=lambda: iter((good, bad)),
    )
    adapter = LocalDeterministicMatcherAdapter()
    try:
        outputs = iter(adapter.iter_partition_results(context))
        assert next(outputs).partition_key == good.partition_key
        with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
            next(outputs)
    finally:
        adapter.close()


@pytest.mark.parametrize("partition_field,mapping", [
    ("amount", {}), ("amount_decimal", {}), ("amount_original", {}),
    ("amount", {"amount_field": "invoice_total"}),
    ("invoice_total", {"amount_field": "invoice_total"}),
])
def test_financial_amount_partition_is_rejected_before_matching(
    partition_field: str, mapping: dict[str, str],
) -> None:
    rule: dict[str, Any] = {**mapping, "partition_fields": [partition_field]}
    left = _record("Left", "left-a", attributes_json={"amount": "1"})
    right = _record("Right", "right-a", attributes_json={"amount": "1.00"})
    with pytest.raises(PostgresReconciliationWorkerError, match="partition"):
        _run(left, right, rule)


@pytest.mark.parametrize("alias", ["currency", "ccy"])
def test_currency_partition_alias_must_be_present_on_every_record(alias: str) -> None:
    left = _record("Left", "left-a", attributes_json={alias: "USD"})
    right = _record("Right", "right-a")
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical|partition"):
        _run(left, right, {"partition_fields": [alias]})


@pytest.mark.parametrize("field,value", [
    ("currency", " USD "), ("ccy", " USD "), ("currency_code", " USD "),
    ("date", " 2026-10-28 "), ("reference", " REF "), ("department", " A "),
    ("department", "A\nB"), ("department", 1), ("department", True),
])
def test_partition_field_cannot_use_noncanonical_text_or_nontext_json(field: str, value: object) -> None:
    attrs = {field: value}
    with pytest.raises(PostgresReconciliationWorkerError, match="(?i)partition"):
        _run(_record("Left", "left-a", attributes_json=attrs),
             _record("Right", "right-a", attributes_json=attrs), {"partition_fields": [field]})


@pytest.mark.parametrize("field", ["id", "source_id"])
def test_partition_identity_cannot_silently_trim_source_id(field: str) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="(?i)partition|identity"):
        _run(_record("Left", " left-a "), _record("Right", "right-a"), {"partition_fields": [field]})


def test_streamed_partition_key_must_equal_every_validated_record_key() -> None:
    invalid_key = _stable_partition_key(["SQL-OTHER"])
    part = ReconciliationInputPartition(
        partition_key=invalid_key,
        left_inputs=(_record("Left", "left-a", attributes_json={"department": "A"}),),
        right_inputs=(_record("Right", "right-a", attributes_json={"department": "A"}),),
    )
    context = ReconciliationExecutionContext(
        run={"rule_json": {"partition_fields": ["department"]}}, left_inputs=(), right_inputs=(),
        heartbeat=lambda _: {}, cancellation_requested=lambda: False, partition_supplier=lambda: iter((part,)),
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="partition"):
        list(LocalDeterministicMatcherAdapter().iter_partition_results(context))


@pytest.mark.parametrize("field,attributes,source_value,key_value", [
    ("department", {"department": "A"}, {}, "A"),
    ("department", {}, {}, None),
    ("currency", {"currency": "USD"}, {}, "USD"),
    ("ccy", {"ccy": "USD"}, {}, "USD"),
    ("currency_code", {}, {}, "USD"),
    ("date", {}, {"date_value": date(2026, 10, 28)}, "2026-10-28"),
    ("reference", {}, {}, "REF"),
    ("id", {}, {}, "shared-id"),
    ("source_id", {}, {}, "shared-id"),
])
def test_supported_streamed_partition_matches_canonical_sql_key(
    field: str, attributes: dict[str, Any], source_value: dict[str, Any], key_value: str | None,
) -> None:
    part = ReconciliationInputPartition(
        partition_key=_stable_partition_key([key_value]),
        left_inputs=(_record("Left", "shared-id", attributes_json=attributes, **source_value),),
        right_inputs=(_record("Right", "shared-id", attributes_json=attributes, **source_value),),
    )
    context = ReconciliationExecutionContext(
        run={"rule_json": {"partition_fields": [field]}}, left_inputs=(), right_inputs=(),
        heartbeat=lambda _: {}, cancellation_requested=lambda: False, partition_supplier=lambda: iter((part,)),
    )
    results = list(LocalDeterministicMatcherAdapter().iter_partition_results(context))
    assert len(results) == 1 and results[0].partition_key == part.partition_key
    assert results[0].results[0]["status"] == "Matched"


@pytest.mark.parametrize("mapping", [
    {"amount_field": "currency"}, {"date_field": "source_id"},
    {"reference_field": "ccy"}, {"amount_field": "shared", "date_field": "shared"},
    {"date_field": "shared", "reference_field": "shared"}, {"date_field": "amount_original"},
])
def test_custom_mapping_cannot_overlap_reserved_or_other_fields(mapping: dict[str, str]) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a"), _record("Right", "right-a"), mapping)


@pytest.mark.parametrize("attribute", ["1e20", "NaN", "Inf", "1" * 129, True])
def test_invalid_or_unbounded_amount_alias_fails_closed(attribute: object) -> None:
    with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
        _run(_record("Left", "left-a", attributes_json={"amount": attribute}), _record("Right", "right-a"))


def test_amount_comparison_is_independent_of_ambient_decimal_traps() -> None:
    record = _record("Left", "left-a", amount_decimal=Decimal("1234.56"),
                     attributes_json={"amount": "(1,234.56)"})
    # The signs conflict even when the ambient context cannot represent 1234.56.
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        with pytest.raises(PostgresReconciliationWorkerError, match="canonical"):
            LocalDeterministicMatcherAdapter._canonical_record(
                record, id_field="id", amount_field="amount", date_field="date", reference_field="reference"
            )


def test_stored_scientific_zero_and_equal_text_are_compared_exactly() -> None:
    record = _record("Left", "left-a", amount_decimal=Decimal("0E-18"), attributes_json={"amount": "0.00"})
    normalized = LocalDeterministicMatcherAdapter._canonical_record(
        record, id_field="id", amount_field="amount", date_field="date", reference_field="reference"
    )
    assert normalized["amount"] == "0.00"
