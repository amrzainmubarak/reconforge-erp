from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest

from reconforge.application.matching_strategies import (
    MatchingStrategyContractError,
    MatchingStrategyRegistry,
    MatchingStrategyRequest,
    canonical_payload,
)
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.indexed_matching_strategy import (
    INDEXED_ONE_TO_ONE_MANIFEST,
    IndexedOneToOneStrategy,
)
from reconforge.platform.matching import MatchingService


def _strategy(tmp_path: Path) -> tuple[IndexedOneToOneStrategy, MatchingService, sqlite3.Connection]:
    db_path = tmp_path / "strategy.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    service = MatchingService(connection)
    return IndexedOneToOneStrategy(service), service, connection


def _request(*, reverse: bool = False) -> MatchingStrategyRequest:
    left = (
        {"id": "L-2", "reference": "INV-002", "amount": "200.00", "date": "2026-01-02"},
        {"id": "L-1", "reference": "INV-001", "amount": "100.00", "date": "2026-01-01"},
    )
    right = (
        {"id": "R-1", "reference": "inv/1", "amount": "100.00", "date": "2026-01-01"},
        {"id": "R-2", "reference": "INV-002", "amount": "200.00", "date": "2026-01-02"},
    )
    return MatchingStrategyRequest(
        left_records=tuple(reversed(left)) if reverse else left,
        right_records=tuple(reversed(right)) if reverse else right,
        amount_tolerance="0",
        date_window_days=0,
    )


def test_indexed_strategy_manifest_is_versioned_bounded_and_registry_addressable(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    try:
        manifest = strategy.manifest
        assert manifest.id == "indexed-composite-one-to-one"
        assert manifest.version == "1.0.0"
        assert manifest.maturity == "beta"
        assert len(manifest.digest) == 64
        assert manifest.limits.max_left_records == 250_000
        registry = MatchingStrategyRegistry((strategy,))
        assert registry.get(manifest.id, manifest.version) is strategy
        assert registry.manifests == (manifest,)
    finally:
        connection.close()


def test_strategy_adapter_preserves_legacy_output_and_adds_reproducible_digests(tmp_path: Path) -> None:
    strategy, service, connection = _strategy(tmp_path)
    request = _request()
    try:
        direct = service.match_records(
            left_records=[dict(record) for record in request.left_records],
            right_records=[dict(record) for record in request.right_records],
            amount_tolerance="0",
            date_window_days=0,
        )
        result = strategy.execute(request)
    finally:
        connection.close()

    assert result.results == direct.results
    assert result.exceptions == direct.exceptions
    assert len(result.input_digest) == len(result.decision_digest) == 64
    assert result.manifest_digest == strategy.manifest.digest
    assert all(item["status"] == "Matched" for item in result.results)
    assert all(item["explanation"] for item in result.results)
    assert all(item["lineage"]["candidate_count"] >= 1 for item in result.results)


def test_strategy_digests_and_decisions_are_record_permutation_invariant(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    try:
        first = strategy.execute(_request())
        shuffled = strategy.execute(_request(reverse=True))
    finally:
        connection.close()

    assert first.input_digest == shuffled.input_digest
    assert first.decision_digest == shuffled.decision_digest
    assert first.results == shuffled.results


def test_strategy_rejects_limits_and_unsafe_numeric_payloads_before_matching(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    try:
        with pytest.raises(MatchingStrategyContractError, match="date-window"):
            strategy.execute(MatchingStrategyRequest(left_records=(), right_records=(), date_window_days=3661))
        with pytest.raises(MatchingStrategyContractError, match="tolerance"):
            strategy.execute(MatchingStrategyRequest(left_records=(), right_records=(), amount_tolerance="NaN"))
        with pytest.raises(MatchingStrategyContractError, match="binary floating"):
            canonical_payload({"amount": 0.1})
        assert canonical_payload({"amount": Decimal("1.2300")}) == {"amount": "1.23"}
    finally:
        connection.close()


def test_registry_rejects_duplicate_or_unknown_strategy_identity(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    try:
        with pytest.raises(MatchingStrategyContractError, match="Duplicate"):
            MatchingStrategyRegistry((strategy, strategy))
        registry = MatchingStrategyRegistry((strategy,))
        with pytest.raises(MatchingStrategyContractError, match="not registered"):
            registry.get(strategy.manifest.id, "2.0.0")
    finally:
        connection.close()


def test_published_strategy_manifest_matches_runtime_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    document = json.loads((root / "docs/architecture/matching-strategies.v1.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "docs/schemas/matching_strategy_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(document)
    published = document["strategies"][0]
    manifest = INDEXED_ONE_TO_ONE_MANIFEST
    assert published == {
        "algorithm": manifest.algorithm,
        "deterministic_tie_break": manifest.deterministic_tie_break,
        "explanation_schema": manifest.explanation_schema,
        "id": manifest.id,
        "limits": manifest.limits.__dict__,
        "maturity": manifest.maturity,
        "supported_modes": list(manifest.supported_modes),
        "version": manifest.version,
    }
