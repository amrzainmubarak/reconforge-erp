"""Artifact bounds preserve exact bytes and the smaller Core financial seal."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from reconforge.application.accrual_deferral_evidence import evidence_chunks, evidence_digest, evidence_size
from reconforge.domain.accrual_deferral import captured_dimensions
from reconforge.domain.finance_posting import MAX_SNAPSHOT_BYTES, FinancePostingError, canonical_json


def test_original_native_fixture_keeps_byte_exact_digest_under_artifact_codec() -> None:
    original = Path(__file__).with_name("fixtures").joinpath("accrual-deferral-native-v1.json").read_bytes()
    value = json.loads(original)
    assert b"".join(evidence_chunks(value)) == original
    assert evidence_digest(value) == hashlib.sha256(original).hexdigest()
    assert evidence_size(value) == len(original)


def test_artifact_over_core_limit_is_exact_and_does_not_relax_core_snapshot_budget() -> None:
    value = {"text": "a" * (MAX_SNAPSHOT_BYTES + 1), "amount_minor": 9_000_000_000_000_000_000, "arabic": "دليل"}
    encoded = b"".join(evidence_chunks(value))
    assert json.loads(encoded) == value and evidence_size(value) == len(encoded)
    with pytest.raises(FinancePostingError):
        canonical_json(value)


def test_explicit_byte_bound_accepts_exact_boundary_then_refuses_one_more_byte() -> None:
    value = {"a": "دليل", "amount_minor": 1}
    exact = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf8")
    assert b"".join(evidence_chunks(value, maximum_bytes=len(exact))) == exact
    with pytest.raises(FinancePostingError, match="byte budget"):
        b"".join(evidence_chunks(value, maximum_bytes=len(exact) - 1))


@pytest.mark.parametrize("value", [1.0, float("nan"), Decimal("1"), {1: "value"}, {"nested": [object()]}])
def test_artifact_refuses_inexact_or_untyped_primitives(value: object) -> None:
    with pytest.raises(FinancePostingError):
        b"".join(evidence_chunks(value))


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_artifact_refuses_invalid_byte_budgets(budget: object) -> None:
    with pytest.raises(FinancePostingError):
        b"".join(evidence_chunks({}, maximum_bytes=budget))  # type: ignore[arg-type]


def test_dimension_capture_accepts_eight_sorted_references_and_refuses_ninth() -> None:
    value = {"D" + str(index): "V" + str(index) for index in reversed(range(8))}
    assert list(captured_dimensions(value)) == sorted(value)
    with pytest.raises(FinancePostingError):
        captured_dimensions({**value, "D8": "V8"})


@pytest.mark.parametrize("value", [{"D": 1}, {" D": "V"}, {"D": "V "}, {"D": ""}, {"D" * 161: "V"}])
def test_dimension_capture_refuses_noncanonical_references(value: object) -> None:
    with pytest.raises(FinancePostingError):
        captured_dimensions(value)
