from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from reconforge.studio.data import _amount_series, _evidence_coverage_cards, _filter_exceptions
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    InvalidAmountError,
    LegacyFinancialInputWarning,
)


def test_amount_series_preserves_invalid_records_as_missing() -> None:
    frame = pd.DataFrame(
        {"amount_impact": ["100", "abc", "", None, "2.50", "-3.00"]},
    )
    amounts = _amount_series(frame)
    assert str(amounts.iloc[0]) == "100"
    assert pd.isna(amounts.iloc[1])
    assert pd.isna(amounts.iloc[2])
    assert pd.isna(amounts.iloc[3])


def test_filter_exceptions_min_amount_rejects_invalid_amount_rows() -> None:
    frame = pd.DataFrame(
        [
            {"exception_id": "a", "amount_impact": "100", "risk_score": "10"},
            {"exception_id": "b", "amount_impact": "abc", "risk_score": "20"},
            {"exception_id": "c", "amount_impact": "2", "risk_score": "30"},
        ],
    )
    filtered = _filter_exceptions(frame, min_amount=10)
    assert list(filtered["exception_id"]) == ["a"]


def test_filter_exceptions_min_amount_preserves_exact_lexical_boundary() -> None:
    frame = pd.DataFrame(
        [
            {"exception_id": "below", "amount_impact": "0.100000000000000003"},
            {"exception_id": "equal", "amount_impact": "0.100000000000000005"},
            {"exception_id": "above", "amount_impact": "0.100000000000000007"},
        ],
    )

    filtered = _filter_exceptions(frame, min_amount="0.100000000000000005", sort="amount_impact")

    assert list(filtered["exception_id"]) == ["above", "equal"]


@pytest.mark.parametrize("threshold", ["-0.01", "1e2", "NaN", "Infinity", "", True, "1" * 101])
def test_filter_exceptions_rejects_invalid_minimum_amount(threshold: object) -> None:
    frame = pd.DataFrame([{"exception_id": "a", "amount_impact": "100"}])

    with pytest.raises(ValueError, match="minimum amount filter"):
        _filter_exceptions(frame, min_amount=threshold)  # type: ignore[arg-type]


def test_filter_exceptions_accepts_exact_decimal_service_boundary() -> None:
    frame = pd.DataFrame([{"exception_id": "a", "amount_impact": "10.000000000000000001"}])

    filtered = _filter_exceptions(frame, min_amount=Decimal("10.000000000000000001"))

    assert list(filtered["exception_id"]) == ["a"]


def test_filter_exceptions_versions_finite_float_service_compatibility() -> None:
    frame = pd.DataFrame([{"exception_id": "a", "amount_impact": "0.1"}])

    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        compatible = _filter_exceptions(
            frame,
            min_amount=0.1,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
    with pytest.raises(InvalidAmountError, match="minimum amount filter"):
        _filter_exceptions(
            frame,
            min_amount=0.1,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert list(compatible["exception_id"]) == ["a"]


def test_filter_exceptions_sorts_invalid_risk_scores_last() -> None:
    frame = pd.DataFrame(
        [
            {"exception_id": "a", "amount_impact": "5", "risk_score": "80"},
            {"exception_id": "b", "amount_impact": "1", "risk_score": "invalid"},
            {"exception_id": "c", "amount_impact": "3", "risk_score": "40"},
            {"exception_id": "d", "amount_impact": "2", "risk_score": "80"},
        ],
    )
    filtered = _filter_exceptions(frame, sort="risk_score")
    assert list(filtered["exception_id"]) == ["a", "d", "c", "b"]


def test_evidence_coverage_cards_counts_high_critical_without_zeroing_scores(tmp_path: Path) -> None:
    output_dir = tmp_path
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir()
    evidence_dir.joinpath("evidence_index.json").write_text(
        json.dumps({"case_count": 1}),
        encoding="utf-8",
    )
    exceptions = pd.DataFrame(
        [
            {"risk_score": "not-a-number", "risk_level": "High"},
            {"risk_score": "62", "risk_level": "low"},
            {"risk_score": "bad", "risk_level": "low"},
        ],
    )
    cards = _evidence_coverage_cards(exceptions, output_dir)
    assert "<strong>2</strong>" in cards
    assert "<strong>50.0%</strong>" in cards
