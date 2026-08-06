from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.application.matching_strategies import MatchingStrategyContractError, MatchingStrategyRequest
from reconforge.infrastructure.duplicate_detection_strategy import (
    DUPLICATE_DETECTION_MANIFEST,
    DuplicateDetectionStrategy,
)


def _request(*, reverse: bool = False, custom_ids: bool = False) -> MatchingStrategyRequest:
    left = (
        {"id": "L-2", "reference": "INV-1", "amount": "10.00", "date": "2026-01-01", "currency": "USD", "partition": "AR"},
        {"id": "L-1", "reference": "INV-1", "amount": "10", "date": "2026-01-01", "currency": "USD", "partition": "AR"},
        {"id": "L-3", "reference": "INV-2", "amount": "20", "date": "2026-01-02", "currency": "USD", "partition": "AR"},
    )
    right = (
        {"id": "R-2", "reference": "SET-1", "amount": "7", "date": "2026-01-01", "currency": "USD", "partition": "BANK"},
        {"id": "R-1", "reference": "SET-1", "amount": "7.0", "date": "2026-01-01", "currency": "USD", "partition": "BANK"},
    )
    if custom_ids:
        left = tuple({**{key: value for key, value in record.items() if key != "id"}, "left_key": record["id"]} for record in left)
        right = tuple({**{key: value for key, value in record.items() if key != "id"}, "right_key": record["id"]} for record in right)
    return MatchingStrategyRequest(
        left_records=tuple(reversed(left)) if reverse else left,
        right_records=tuple(reversed(right)) if reverse else right,
        left_id_field="left_key" if custom_ids else "id",
        right_id_field="right_key" if custom_ids else "id",
        mode="duplicate-detection",
    )


def test_duplicate_detection_groups_exact_canonical_duplicates_and_preserves_occurrences() -> None:
    strategy = DuplicateDetectionStrategy()
    result = strategy.execute(_request())

    assert result.results
    assert result.exceptions
    duplicate = next(item for item in result.results if item["status"] == "duplicate" and item["side"] == "left")
    assert duplicate["record_ids"] == ("L-1", "L-2")
    assert duplicate["occurrence_ids"] == ("L-1#occurrence:1", "L-2#occurrence:2")
    assert duplicate["duplicate_count"] == 2
    assert result.exceptions[0]["reason_code"] == "DUPLICATE_FINGERPRINT_GROUP"


def test_duplicate_detection_digest_is_permutation_invariant_and_side_scoped() -> None:
    strategy = DuplicateDetectionStrategy()
    first = strategy.execute(_request())
    shuffled = strategy.execute(_request(reverse=True))

    assert first.input_digest == shuffled.input_digest
    assert first.decision_digest == shuffled.decision_digest
    assert first.results == shuffled.results
    assert {item["side"] for item in first.results} == {"left", "right"}


def test_duplicate_detection_supports_explicit_identity_fields() -> None:
    result = DuplicateDetectionStrategy().execute(_request(custom_ids=True))
    assert any(item["record_ids"] == ("L-1", "L-2") for item in result.results)
    assert any(item["record_ids"] == ("R-1", "R-2") for item in result.results)


def test_duplicate_detection_rejects_binary_float_and_duplicate_identity() -> None:
    strategy = DuplicateDetectionStrategy()
    with pytest.raises(MatchingStrategyContractError, match="binary floating"):
        strategy.execute(
            MatchingStrategyRequest(
                left_records=({"id": "L-1", "amount": 0.1},),
                right_records=(),
                mode="duplicate-detection",
            )
        )
    with pytest.raises(MatchingStrategyContractError, match="identities"):
        strategy.execute(
            MatchingStrategyRequest(
                left_records=(
                    {"id": "L-1", "amount": "1"},
                    {"id": "L-1", "amount": "1"},
                ),
                right_records=(),
                mode="duplicate-detection",
            )
        )


def test_duplicate_detection_fails_closed_at_published_budget() -> None:
    strategy = DuplicateDetectionStrategy()
    request = MatchingStrategyRequest(
        left_records=tuple({"id": f"L-{index}", "amount": "1"} for index in range(250_001)),
        right_records=(),
        mode="duplicate-detection",
    )
    with pytest.raises(MatchingStrategyContractError, match="input record limit"):
        strategy.execute(request)


def test_duplicate_detection_manifest_is_published_in_architecture_document() -> None:
    document = json.loads(Path("docs/architecture/matching-strategies.v1.json").read_text(encoding="utf-8"))
    published = next(item for item in document["strategies"] if item["id"] == DUPLICATE_DETECTION_MANIFEST.id)
    assert published == {
        "algorithm": DUPLICATE_DETECTION_MANIFEST.algorithm,
        "deterministic_tie_break": DUPLICATE_DETECTION_MANIFEST.deterministic_tie_break,
        "explanation_schema": DUPLICATE_DETECTION_MANIFEST.explanation_schema,
        "id": DUPLICATE_DETECTION_MANIFEST.id,
        "limits": DUPLICATE_DETECTION_MANIFEST.limits.as_dict,
        "maturity": DUPLICATE_DETECTION_MANIFEST.maturity,
        "supported_modes": list(DUPLICATE_DETECTION_MANIFEST.supported_modes),
        "version": DUPLICATE_DETECTION_MANIFEST.version,
    }
