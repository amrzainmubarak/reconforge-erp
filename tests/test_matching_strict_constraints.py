from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from itertools import permutations
from typing import Any

import pytest

from reconforge.application.matching import DeterministicMatchOutput
from reconforge.platform.common import PlatformError
from reconforge.reconciliation.deterministic_engine import (
    LEGACY_CONSTRAINT_POLICY,
    MAX_CONSTRAINT_REJECTION_EXAMPLES,
    MAX_STRICT_DECIMAL_PRECISION,
    MAX_STRICT_FINANCIAL_INPUT_CHARS,
    STRICT_ONE_TO_ONE_CONSTRAINT_POLICY,
    DeterministicMatchingEngine,
)


def _engine(**limits: int) -> DeterministicMatchingEngine:
    def currency(code: str) -> tuple[int | None, str | None]:
        return {"USD": (2, None), "EUR": (2, None), "KWD": (3, None), "JPY": (0, None), "XTS": (None, None)}.get(code, (None, "UNKNOWN_CURRENCY"))

    return DeterministicMatchingEngine(currency, **limits)


def _row(identifier: str, **values: Any) -> dict[str, Any]:
    return {"id": identifier, "reference": "A", "date": "2026-01-01", "amount": "100.00", "currency": "USD", "account": "cash", **values}


def _strict(left: list[dict[str, Any]], right: list[dict[str, Any]], **options: Any) -> DeterministicMatchOutput:
    return _engine().match_records(left_records=left, right_records=right, constraint_policy=STRICT_ONE_TO_ONE_CONSTRAINT_POLICY, **options)


def _matches(output: DeterministicMatchOutput) -> list[dict[str, Any]]:
    return [row for row in output.results if row["status"] == "Matched"]


def _left(output: DeterministicMatchOutput, identifier: str = "L") -> dict[str, Any]:
    return next(row for row in output.results if row.get("left_id") == identifier)


def test_default_legacy_results_and_digest_are_unchanged() -> None:
    left = [_row("L-1", amount="100.00"), _row("L-2", amount="200.00", reference="B")]
    right = [_row("R-1", amount="999.00"), _row("R-2", amount="200.00", reference="B", date="2026-01-03")]
    options = {"left_records": left, "right_records": right, "exact_fields": "account"}
    output = _engine().match_records(**options)
    assert output == _engine().match_records(**options, constraint_policy=LEGACY_CONSTRAINT_POLICY)
    encoded = json.dumps(asdict(output), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(encoded).hexdigest() == "85556fae9ea7db8e9080be8afb12642103f06b5b1f5f366ce3fe9383f6847771"
    assert sorted(row["confidence"] for row in _matches(output)) == ["0.70", "0.85"]
    assert all("constraint_policy" not in row["lineage"] for row in output.results)
    assert not _matches(_strict(left, right, exact_fields="account"))


@pytest.mark.parametrize(("amount", "expected"), [("99.99", True), ("100.00", True), ("100.01", True), ("100.02", False)])
def test_amount_tolerance_is_a_hard_inclusive_bound(amount: str, expected: bool) -> None:
    output = _strict([_row("L")], [_row("R", amount=amount)], exact_fields="account", amount_tolerance="0.01")
    assert bool(_matches(output)) is expected
    if not expected:
        assert _left(output)["lineage"]["constraint_rejection_reason_counts"] == {"AMOUNT_TOLERANCE_EXCEEDED": 1}


@pytest.mark.parametrize(("currency", "left", "right", "tolerance"), [
    ("JPY", "100", "101", "1"), ("KWD", "100.001", "100.002", "0.001"),
])
def test_currency_scale_is_not_assumed_to_be_two(currency: str, left: str, right: str, tolerance: str) -> None:
    output = _strict([_row("L", amount=left, currency=currency)], [_row("R", amount=right, currency=currency)], amount_tolerance=tolerance)
    assert len(_matches(output)) == 1
    assert Decimal(_matches(output)[0]["amount_difference"]) == Decimal(tolerance)


@pytest.mark.parametrize(("day", "expected"), [("2025-12-31", True), ("2026-01-02", True), ("2026-01-03", False)])
def test_date_window_is_a_hard_inclusive_bound(day: str, expected: bool) -> None:
    output = _strict([_row("L")], [_row("R", date=day)], date_window_days=1, exact_fields="account")
    assert bool(_matches(output)) is expected
    if not expected:
        assert _left(output)["lineage"]["constraint_rejection_reason_counts"] == {"DATE_WINDOW_EXCEEDED": 1}


@pytest.mark.parametrize("right_values", [{"date": "2026-01-02"}, {"account": "other"}, {"valid": False}, {"date": None}])
def test_ineligible_best_candidate_is_removed_before_assignment_and_alternative_is_matched(right_values: dict[str, Any]) -> None:
    left = [_row("L")]
    right = [_row("BAD", **right_values), _row("GOOD", amount="120.00")]
    output = _strict(left, right, exact_fields="account", amount_tolerance="20")
    assert [(row["left_id"], row["right_id"]) for row in _matches(output)] == [("L", "GOOD")]
    assert _left(output)["lineage"]["constraint_rejected_candidate_count"] == 1


@pytest.mark.parametrize("right_values", [{"currency": "EUR"}, {"currency": ""}, {"currency": "UNKNOWN"}])
def test_currency_mismatch_missing_or_unknown_cannot_match(right_values: dict[str, Any]) -> None:
    assert not _matches(_strict([_row("L")], [_row("R", **right_values)]))


def test_missing_currency_on_both_sides_is_not_an_implicit_shared_currency() -> None:
    output = _strict([_row("L", currency="")], [_row("R", currency="")])
    assert not _matches(output)
    assert _left(output)["lineage"]["constraint_rejection_reason_counts"] == {"MISSING_CURRENCY": 1}


def test_exact_fields_compare_individually_and_do_not_accept_delimiter_collisions() -> None:
    output = _strict([_row("L", account="A|B", entity="C")], [_row("R", account="A", entity="B|C")], exact_fields="account,entity")
    assert not _matches(output)
    assert _left(output)["lineage"]["constraint_rejection_reason_counts"] == {"EXACT_FIELD_MISMATCH": 1}


def test_missing_exact_fields_do_not_match_each_other() -> None:
    output = _strict([_row("L")], [_row("R")], exact_fields="unprovided")
    assert not _matches(output)
    assert _left(output)["lineage"]["constraint_rejection_reason_counts"] == {"EXACT_FIELD_MISSING": 1}


@pytest.mark.parametrize("negative", [False, True])
def test_exact_large_values_and_fingerprints_ignore_ambient_decimal_precision(negative: bool) -> None:
    amount = "123456789012345678901234567890.12345678"
    good = "123456789012345678901234567890.12345679"
    bad = "123456789012345678901234567890.12345680"
    left = [_row("L", amount=f"({amount})" if negative else amount, currency="XTS", marker=Decimal(amount))]
    right = [_row("GOOD", amount=f"-{good}" if negative else good, currency="XTS"), _row("BAD", amount=f"-{bad}" if negative else bad, currency="XTS")]
    expected = _strict(left, right, amount_tolerance="0.00000001", exact_fields="account")
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        actual = _strict(left, right, amount_tolerance="0.00000001", exact_fields="account")
        assert context.prec == 2
        assert context.rounding == ROUND_DOWN
        assert context.traps[Inexact]
    assert actual == expected
    assert [(row["right_id"], row["amount_difference"]) for row in _matches(actual)] == [("GOOD", "0.00000001")]
    assert _left(actual)["lineage"]["constraint_rejections"][0]["amount_difference"] == "0.00000002"


def test_amount_range_index_retains_boundary_candidate_under_low_precision() -> None:
    left = [_row("L", amount="12345678901234567890.12345678", currency="XTS")]
    right = [_row("EDGE", amount="12345678901234567890.12345679", currency="XTS", reference="DIFFERENT"), _row("OUT", amount="12345678901234567890.12345680", currency="XTS", reference="DIFFERENT")]
    with localcontext() as context:
        context.prec = 2
        output = _strict(left, right, amount_tolerance="0.00000001")
    lineage = _left(output)["lineage"]
    assert lineage["constraint_evaluated_candidate_count"] == 1
    assert lineage["constraint_rejections"][0]["right_id"] == "EDGE"
    # Strict constraints do not turn a low-scoring candidate into an accepted match.
    assert lineage["constraint_rejection_reason_counts"] == {"CONFIDENCE_BELOW_THRESHOLD": 1}


def test_rejection_lineage_is_bounded_complete_and_permutation_stable() -> None:
    left = [_row("L")]
    right = [_row(f"R-{i}", amount="200.00", date="2026-01-03") for i in range(8)]
    output = _strict(left, right)
    lineage = _left(output)["lineage"]
    assert lineage["constraint_policy"] == "strict-one-to-one-v1"
    assert lineage["constraints"] == {"amount_tolerance": "0", "date_window_days": 0, "exact_fields": [], "currency": "explicit-equal-currency"}
    assert lineage["constraint_evaluated_candidate_count"] == 8
    assert lineage["constraint_rejected_candidate_count"] == 8
    assert lineage["constraint_rejection_reason_counts"] == {"AMOUNT_TOLERANCE_EXCEEDED": 8, "DATE_WINDOW_EXCEEDED": 8}
    assert len(lineage["constraint_rejections"]) == MAX_CONSTRAINT_REJECTION_EXAMPLES == 3
    assert lineage["constraint_rejections"][0]["explanation"] == (
        "The exact amount difference exceeds the configured tolerance. "
        "The date difference exceeds the configured window."
    )
    assert lineage["constraint_rejections_truncated"] is True
    assert output == _strict(left, list(reversed(right)))


def test_assignment_with_duplicates_remains_one_to_one_and_permutation_stable() -> None:
    left = [_row("L-1"), _row("L-1"), _row("L-2", amount="101.00")]
    right = [_row("R-1"), _row("R-1"), _row("R-2", amount="101.00")]
    expected = _strict(left, right, amount_tolerance="1")
    assert len(_matches(expected)) == 3
    assert len({row["right_id"] for row in _matches(expected)}) == 3
    for ordering in permutations(right):
        assert _strict(list(reversed(left)), list(ordering), amount_tolerance="1") == expected


@pytest.mark.parametrize(("limits", "count", "reason"), [
    ({"max_candidates_per_left_record": 2}, 3, "max_candidates_per_left_record"),
    ({"max_total_candidate_evaluations": 2}, 3, "max_total_candidate_evaluations"),
])
def test_candidate_limits_remain_fail_closed_in_strict_mode(limits: dict[str, int], count: int, reason: str) -> None:
    output = _engine(**limits).match_records(left_records=[_row("L")], right_records=[_row(f"R-{i}") for i in range(count)], constraint_policy=STRICT_ONE_TO_ONE_CONSTRAINT_POLICY)
    result = _left(output)
    assert not _matches(output)
    assert result["status"] == "Ambiguous"
    assert result["reason_code"] == "CANDIDATE_BUDGET_EXCEEDED"
    assert result["lineage"]["exceeded_limit"] == reason
    assert result["lineage"]["constraint_policy"] == STRICT_ONE_TO_ONE_CONSTRAINT_POLICY
    assert result["lineage"]["constraint_evaluated_candidate_count"] == 0


@pytest.mark.parametrize("flag", ["allow_many_to_one", "allow_one_to_many", "allow_many_to_many"])
def test_strict_policy_rejects_every_grouped_flag(flag: str) -> None:
    with pytest.raises(PlatformError, match="grouped"):
        _strict([], [], **{flag: True})


@pytest.mark.parametrize("policy", [None, "", "strict", 1, {}])
def test_unknown_constraint_policy_fails_before_processing(policy: Any) -> None:
    with pytest.raises(PlatformError, match="constraint policy"):
        _engine().match_records(left_records=[], right_records=[], constraint_policy=policy)


@pytest.mark.parametrize("window", [-1, True, 1.5, "1", None])
def test_invalid_strict_date_window_is_rejected(window: Any) -> None:
    with pytest.raises(PlatformError, match="date window"):
        _strict([], [], date_window_days=window)


@pytest.mark.parametrize("tolerance", ["-0.01", "NaN", "Infinity", "", None, 0.01])
def test_invalid_strict_tolerance_is_rejected_without_implicit_zero(tolerance: Any) -> None:
    with pytest.raises(PlatformError, match="Invalid financial amount"):
        _strict([_row("L")], [_row("R")], amount_tolerance=tolerance)


@pytest.mark.parametrize("value", [
    "9" * (MAX_STRICT_FINANCIAL_INPUT_CHARS + 1),
    10**MAX_STRICT_FINANCIAL_INPUT_CHARS,
    Decimal("9" * (MAX_STRICT_FINANCIAL_INPUT_CHARS + 1)),
    Decimal("1e999999999"),
    Decimal("1e-999999999"),
    Decimal("0e-999999999"),
    Decimal("1e4096"),
])
@pytest.mark.parametrize("field", ["amount", "tolerance", "decimal_identity"])
def test_strict_input_budgets_fail_before_matching(value: Any, field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if field == "decimal_identity" and not isinstance(value, Decimal):
        value = Decimal(value)
    engine = _engine()

    def forbidden(**options: Any) -> DeterministicMatchOutput:
        pytest.fail("oversized strict input reached matching")

    monkeypatch.setattr(engine, "_match_records", forbidden)
    row = _row("L", **({field if field == "amount" else "marker": value} if field != "tolerance" else {}))
    options = {"amount_tolerance": value} if field == "tolerance" else {}
    with pytest.raises(PlatformError, match="Strict matching .*limit"):
        engine.match_records(left_records=[row], right_records=[], constraint_policy=STRICT_ONE_TO_ONE_CONSTRAINT_POLICY, **options)


def test_combined_decimal_span_is_bounded_before_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()

    def forbidden(**options: Any) -> DeterministicMatchOutput:
        pytest.fail("oversized derived precision reached matching")

    monkeypatch.setattr(engine, "_match_records", forbidden)
    assert MAX_STRICT_DECIMAL_PRECISION == 4096
    with pytest.raises(PlatformError, match="derived arithmetic precision"):
        engine.match_records(
            left_records=[_row("L", amount=Decimal("1e3000"))],
            right_records=[_row("R", amount=Decimal("1e-2000"))],
            constraint_policy=STRICT_ONE_TO_ONE_CONSTRAINT_POLICY,
        )


def test_strict_budgets_allow_128_digit_financial_values() -> None:
    amount = "9" * 128 + ".12"
    output = _strict([_row("L", amount=amount)], [_row("R", amount=amount)])
    assert [(row["left_id"], row["right_id"], row["amount_difference"]) for row in _matches(output)] == [("L", "R", "0.00")]
