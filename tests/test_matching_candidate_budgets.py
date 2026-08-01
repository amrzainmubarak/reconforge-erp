from __future__ import annotations

import sqlite3
from importlib import import_module
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.platform.matching import MatchingService

matching_module = import_module("reconforge.infrastructure.sqlite_matching")


def _service(tmp_path: Path) -> tuple[MatchingService, sqlite3.Connection]:
    database = tmp_path / "candidate-budget.db"
    run_migrations(database)
    connection = connect(database, require_exists=True)
    return MatchingService(connection), connection


def _record(side: str, index: int) -> dict[str, str]:
    return {
        "id": f"{side}-{index}",
        "reference": "DENSE-REFERENCE",
        "amount": "100.00",
        "date": "2026-01-01",
    }


def test_per_record_candidate_budget_produces_ambiguity_not_partial_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matching_module, "MAX_CANDIDATES_PER_LEFT_RECORD", 2)
    service, connection = _service(tmp_path)
    try:
        output = service.match_records(
            left_records=[_record("L", 1)],
            right_records=[_record("R", index) for index in range(3)],
        )
    finally:
        connection.close()

    left = next(item for item in output.results if item.get("left_id") == "L-1")
    assert left["status"] == "Ambiguous"
    assert left["reason_code"] == "CANDIDATE_BUDGET_EXCEEDED"
    assert left["lineage"]["candidate_count"] == 3
    assert not any(item["status"] == "Matched" for item in output.results)
    exception = output.exceptions[0]
    assert exception["exception_type"] == "matching_ambiguity"
    assert exception["evidence"]["candidate_policy"] == "indexed-candidate-budget-v1"
    assert exception["evidence"]["exceeded_limit"] == "max_candidates_per_left_record"
    assert exception["evidence"]["limit"] == 2
    assert exception["evidence"]["exclusion_reason"] == "Per-record candidate ceiling exceeded."


def test_total_search_budget_is_deterministic_and_leaves_later_record_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matching_module, "MAX_CANDIDATES_PER_LEFT_RECORD", 10)
    monkeypatch.setattr(matching_module, "MAX_TOTAL_CANDIDATE_EVALUATIONS", 2)
    service, connection = _service(tmp_path)
    left = [_record("L", 2), _record("L", 1)]
    right = [_record("R", 2), _record("R", 1)]
    try:
        first = service.match_records(left_records=left, right_records=right)
        second = service.match_records(left_records=list(reversed(left)), right_records=list(reversed(right)))
    finally:
        connection.close()

    def signature(output):
        return sorted(
            (str(item.get("left_id", "")), str(item["status"]), str(item.get("reason_code", "")))
            for item in output.results
            if item.get("left_id")
        )

    assert signature(first) == signature(second)
    assert sum(item["status"] == "Matched" for item in first.results) == 1
    ambiguous = next(item for item in first.results if item["status"] == "Ambiguous")
    assert ambiguous["lineage"]["rejection_reasons"] == ["Run candidate-evaluation ceiling exceeded."]
