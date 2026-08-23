from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from reconforge.application.matching_strategies import (
    GroupedMatchBudget,
    MatchingStrategyContractError,
    MatchingStrategyRegistry,
    MatchingStrategyRequest,
    MatchingStrategyResult,
    canonical_payload,
    replay_result_envelope,
    replay_strategy_result,
    request_digest,
    result_digest,
)
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.carry_forward_strategy import (
    CARRY_FORWARD_FIFO_MANIFEST,
    CarryForwardFifoStrategy,
)
from reconforge.infrastructure.grouped_matching_strategy import (
    GROUPED_SUBSET_SUM_MANIFEST,
    GroupedSubsetSumStrategy,
)
from reconforge.infrastructure.indexed_matching_strategy import (
    INDEXED_ONE_TO_ONE_MANIFEST,
    IndexedOneToOneStrategy,
)
from reconforge.infrastructure.matching_strategy_registry import build_matching_strategy_registry
from reconforge.infrastructure.reversal_matching_strategy import (
    REVERSAL_PAIRING_MANIFEST,
    ReversalPairingStrategy,
)
from reconforge.platform.matching import MatchingService


def _strategy(tmp_path: Path) -> tuple[IndexedOneToOneStrategy, MatchingService, sqlite3.Connection]:
    db_path = tmp_path / "strategy.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    service = MatchingService(connection)
    return IndexedOneToOneStrategy(service), service, connection


def _request(*, reverse: bool = False, mode: str = "one-to-one") -> MatchingStrategyRequest:
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
        mode=mode,
    )


def test_indexed_strategy_manifest_is_versioned_bounded_and_registry_addressable(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    try:
        manifest = strategy.manifest
        assert manifest.id == "indexed-composite-one-to-one"
        assert manifest.version == "1.0.0"
        assert manifest.maturity == "beta"
        assert len(manifest.digest) == 64
        assert manifest.digest == "e3760bb991ea1edef3dbb2448e8e2b92063147b8dd9261433cac7cfa7fda5da3"
        assert manifest.limits.max_left_records == 250_000
        assert manifest.limits.max_candidates_per_record == 10_000
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


def test_strategy_result_json_envelope_round_trip_is_closed_and_replay_verified(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    request = _request()
    try:
        result = strategy.execute(request)
    finally:
        connection.close()

    payload = json.loads(json.dumps(result.to_payload(), sort_keys=True))
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/schemas/matching_strategy_result_envelope.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    restored = MatchingStrategyResult.from_payload(payload)
    restored.verify_payload(
        request,
        manifest_digest=strategy.manifest.digest,
        strategy_id=strategy.manifest.id,
        strategy_version=strategy.manifest.version,
    )
    assert restored.to_payload() == payload
    assert replay_result_envelope(result, request, manifest=strategy.manifest) == restored
    assert replay_strategy_result(strategy, request, result) == restored

    with pytest.raises(MatchingStrategyContractError, match="not closed"):
        MatchingStrategyResult.from_payload({**payload, "unexpected": True})
    with pytest.raises(MatchingStrategyContractError, match="schema version"):
        MatchingStrategyResult.from_payload({**payload, "schema_version": 2})
    with pytest.raises(MatchingStrategyContractError, match="digest fields"):
        MatchingStrategyResult.from_payload({**payload, "decision_digest": "not-a-digest"})
    with pytest.raises(MatchingStrategyContractError, match="identity"):
        restored.verify_payload(
            request,
            manifest_digest=strategy.manifest.digest,
            strategy_id="tampered-strategy",
            strategy_version=strategy.manifest.version,
        )
    changed_results = tuple({**item, "status": "tampered"} for item in result.results)
    changed = MatchingStrategyResult(
        strategy_id=result.strategy_id,
        strategy_version=result.strategy_version,
        manifest_digest=result.manifest_digest,
        input_digest=result.input_digest,
        decision_digest=result_digest(
            manifest_digest=result.manifest_digest,
            input_digest=result.input_digest,
            results=changed_results,
            exceptions=result.exceptions,
        ),
        results=changed_results,
        exceptions=result.exceptions,
        explanation_schema=result.explanation_schema,
    )
    with pytest.raises(MatchingStrategyContractError, match="differs"):
        replay_strategy_result(strategy, request, changed)


def test_cli_validates_result_envelope_without_external_calls(tmp_path: Path) -> None:
    strategy = GroupedSubsetSumStrategy()
    request = MatchingStrategyRequest(
        left_records=({"id": "L1", "amount": "10", "currency": "USD", "date": "2026-01-01", "partition": "P1"},),
        right_records=({"id": "R1", "amount": "10", "currency": "USD", "date": "2026-01-01", "partition": "P1"},),
        mode="many-to-many",
    )
    envelope_path = tmp_path / "result.json"
    envelope_path.write_text(json.dumps(strategy.execute(request).to_payload()), encoding="utf-8")
    result = CliRunner().invoke(app, ["match", "validate-result-envelope", str(envelope_path)])
    assert result.exit_code == 0, result.stdout
    assert "external_calls" in result.stdout
    assert "replay_request_required" in result.stdout


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


def test_carry_forward_strategy_is_published_bounded_and_permutation_invariant() -> None:
    strategy = CarryForwardFifoStrategy()
    request = MatchingStrategyRequest(
        left_records=(
            {"id": "O-2", "amount": "20", "date": "2026-01-02", "currency": "USD", "partition": "bank-1"},
            {"id": "O-1", "amount": "100", "date": "2026-01-01", "currency": "USD", "partition": "bank-1"},
        ),
        right_records=({"id": "S-1", "amount": "120", "date": "2026-01-03", "currency": "USD", "partition": "bank-1"},),
        mode="carry-forward",
        date_window_days=30,
    )
    shuffled = MatchingStrategyRequest(
        left_records=tuple(reversed(request.left_records)),
        right_records=request.right_records,
        mode=request.mode,
        date_window_days=request.date_window_days,
    )
    first = strategy.execute(request)
    second = strategy.execute(shuffled)
    assert strategy.manifest == CARRY_FORWARD_FIFO_MANIFEST
    assert first.input_digest == second.input_digest
    assert first.results == second.results
    assert first.results[0]["status"] == "allocated"


def test_sequence_window_strategy_matches_contiguous_records_and_exposes_bounds() -> None:
    strategy = CarryForwardFifoStrategy()
    request = MatchingStrategyRequest(
        left_records=(
            {"id": "O-2", "amount": "60", "date": "2026-01-02", "currency": "USD", "partition": "bank-1"},
            {"id": "O-1", "amount": "40", "date": "2026-01-01", "currency": "USD", "partition": "bank-1"},
            {"id": "O-3", "amount": "20", "date": "2026-01-03", "currency": "USD", "partition": "bank-1"},
        ),
        right_records=(
            {"id": "S-1", "amount": "100", "date": "2026-01-04", "currency": "USD", "partition": "bank-1"},
        ),
        mode="sequence-window",
        date_window_days=10,
    )
    result = strategy.execute(request)
    assert result.results[0]["status"] == "allocated"
    assert [item["obligation_id"] for item in result.results[0]["allocations"]] == ["O-1", "O-2"]
    assert strategy.manifest.limits.max_left_group_cardinality == 16


def test_sequence_window_strategy_returns_ambiguity_instead_of_guessing() -> None:
    strategy = CarryForwardFifoStrategy()
    result = strategy.execute(
        MatchingStrategyRequest(
            left_records=tuple(
                {"id": f"O-{index}", "amount": "50", "date": f"2026-01-0{index}", "currency": "USD", "partition": "bank-1"}
                for index in range(1, 5)
            ),
            right_records=(
                {"id": "S-1", "amount": "100", "date": "2026-01-05", "currency": "USD", "partition": "bank-1"},
            ),
            mode="sequence-window",
            date_window_days=10,
        )
    )
    assert result.results[0]["status"] == "ambiguous"
    assert result.results[0]["reason_code"] == "SEQUENCE_WINDOW_AMBIGUOUS_EQUAL_COST"
    assert result.exceptions[0]["reason_code"] == "SEQUENCE_WINDOW_AMBIGUOUS_EQUAL_COST"


def test_carry_forward_strategy_is_published_in_architecture_document() -> None:
    document = json.loads(Path("docs/architecture/matching-strategies.v1.json").read_text(encoding="utf-8"))
    published = document["strategies"][2]
    assert published["id"] == CARRY_FORWARD_FIFO_MANIFEST.id
    assert published["version"] == CARRY_FORWARD_FIFO_MANIFEST.version
    assert published["supported_modes"] == list(CARRY_FORWARD_FIFO_MANIFEST.supported_modes)
    assert published["limits"] == CARRY_FORWARD_FIFO_MANIFEST.limits.as_dict


def test_reversal_strategy_is_bounded_and_permutation_invariant() -> None:
    strategy = ReversalPairingStrategy()
    request = MatchingStrategyRequest(
        left_records=(
            {"id": "J-1", "amount": "100", "date": "2026-01-01", "currency": "USD", "partition": "ledger-1"},
            {"id": "J-2", "amount": "50", "date": "2026-01-02", "currency": "USD", "partition": "ledger-1"},
        ),
        right_records=({"id": "R-1", "amount": "-100", "date": "2026-01-03", "currency": "USD", "partition": "ledger-1", "reversal_of": "J-1"},),
        mode="reversal-pairing",
        date_window_days=30,
    )
    shuffled = MatchingStrategyRequest(
        left_records=tuple(reversed(request.left_records)),
        right_records=request.right_records,
        mode=request.mode,
        date_window_days=request.date_window_days,
    )
    first = strategy.execute(request)
    second = strategy.execute(shuffled)
    assert strategy.manifest == REVERSAL_PAIRING_MANIFEST
    assert first.input_digest == second.input_digest
    assert first.results == second.results
    assert first.results[0]["status"] == "matched"


def test_reversal_strategy_is_published_in_architecture_document() -> None:
    document = json.loads(Path("docs/architecture/matching-strategies.v1.json").read_text(encoding="utf-8"))
    published = document["strategies"][3]
    assert published["id"] == REVERSAL_PAIRING_MANIFEST.id
    assert published["version"] == REVERSAL_PAIRING_MANIFEST.version
    assert published["supported_modes"] == list(REVERSAL_PAIRING_MANIFEST.supported_modes)
    assert published["limits"] == REVERSAL_PAIRING_MANIFEST.limits.as_dict


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


def test_complete_strategy_registry_covers_every_published_strategy_family(tmp_path: Path) -> None:
    _strategy_instance, service, connection = _strategy(tmp_path)
    try:
        registry = build_matching_strategy_registry(service)
        manifest_ids = {manifest.id for manifest in registry.manifests}
        assert manifest_ids == {
            "indexed-composite-one-to-one",
            "bounded-grouped-subset-sum",
            "bounded-duplicate-detection",
            "bounded-carry-forward-fifo",
            "bounded-reversal-pairing",
        }
        published = json.loads(
            (Path(__file__).resolve().parents[1] / "docs/architecture/matching-strategies.v1.json").read_text(
                encoding="utf-8"
            )
        )
        assert {str(item["id"]) for item in published["strategies"]} == manifest_ids
        for manifest in registry.manifests:
            assert registry.get(manifest.id, manifest.version).manifest == manifest
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
        "limits": manifest.limits.as_dict,
        "maturity": manifest.maturity,
        "supported_modes": list(manifest.supported_modes),
        "version": manifest.version,
    }
    grouped_published = document["strategies"][1]
    grouped = GROUPED_SUBSET_SUM_MANIFEST
    assert grouped_published == {
        "algorithm": grouped.algorithm,
        "deterministic_tie_break": grouped.deterministic_tie_break,
        "explanation_schema": grouped.explanation_schema,
        "id": grouped.id,
        "limits": grouped.limits.as_dict,
        "maturity": grouped.maturity,
        "supported_modes": list(grouped.supported_modes),
        "version": grouped.version,
    }


def test_grouped_strategy_is_registered_versioned_and_permutation_invariant() -> None:
    strategy = GroupedSubsetSumStrategy()
    request = MatchingStrategyRequest(
        left_records=({"id": "L1", "amount": "100", "currency": "USD", "date": "2026-01-10", "partition": "AR"},),
        right_records=(
            {"id": "R2", "amount": "60", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            {"id": "R1", "amount": "40", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
        ),
        mode="one-to-many",
    )

    first = strategy.execute(request)
    second = strategy.execute(
        MatchingStrategyRequest(
            left_records=request.left_records,
            right_records=tuple(reversed(request.right_records)),
            mode="one-to-many",
        )
    )

    assert first == second
    assert first.results[0]["left_record_ids"] == ("L1",)
    registry = MatchingStrategyRegistry((strategy,))
    assert registry.get(strategy.manifest.id, strategy.manifest.version) is strategy


def test_strategy_result_replay_verifier_rejects_manifest_input_and_output_tampering() -> None:
    strategy = GroupedSubsetSumStrategy()
    request = MatchingStrategyRequest(
        left_records=(
            {"id": "L1", "amount": "100", "currency": "USD", "date": "2026-01-01", "partition": "AR"},
        ),
        right_records=(
            {"id": "R1", "amount": "40", "currency": "USD", "date": "2026-01-01", "partition": "AR"},
            {"id": "R2", "amount": "60", "currency": "USD", "date": "2026-01-01", "partition": "AR"},
        ),
        mode="one-to-many",
    )
    result = strategy.execute(request)

    assert result.strategy_id == strategy.manifest.id
    assert result.strategy_version == strategy.manifest.version
    result.verify_against(request, manifest_digest=strategy.manifest.digest)

    with pytest.raises(MatchingStrategyContractError, match="manifest digest"):
        result.verify_against(request, manifest_digest="0" * 64)

    with pytest.raises(MatchingStrategyContractError, match="identity"):
        result.verify_against(request, manifest_digest=strategy.manifest.digest, strategy_id="tampered")

    with pytest.raises(MatchingStrategyContractError, match="version"):
        result.verify_against(request, manifest_digest=strategy.manifest.digest, strategy_version="9.9.9")

    changed_request = replace(
        request,
        left_records=({**request.left_records[0], "amount": "101"},) + request.left_records[1:],
    )
    with pytest.raises(MatchingStrategyContractError, match="input digest"):
        result.verify_against(changed_request, manifest_digest=strategy.manifest.digest)

    tampered = replace(result, results=tuple({**result.results[0], "status": "unmatched"} for _ in (0,)))
    with pytest.raises(MatchingStrategyContractError, match="decision digest"):
        tampered.verify_against(request, manifest_digest=strategy.manifest.digest)


def test_matching_result_replay_verifier_is_in_source_distribution_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/adr/0404-matching-result-replay-verification.md" in manifest
    assert "include tests/test_matching_strategy_contract.py" in manifest


def test_grouped_strategy_supports_fee_aware_netting_fields_and_request_digest_variants() -> None:
    strategy = GroupedSubsetSumStrategy()
    request = MatchingStrategyRequest(
        left_records=({"id": "L1", "amount": "120.00", "currency": "USD", "date": "2026-01-10", "partition": "AR", "left_fee": "20.00"},),
        right_records=(
            {"id": "R1", "amount": "80.00", "currency": "USD", "date": "2026-01-10", "partition": "AR", "right_fee": "10.00"},
            {"id": "R2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR", "right_fee": "10.00"},
        ),
        mode="one-to-many",
        netting_mode="net",
        left_fee_field="left_fee",
        right_fee_field="right_fee",
    )
    result = strategy.execute(request)

    assert result.results[0]["status"] == "matched"
    assert result.results[0]["netting_mode"] == "net"
    assert result.results[0]["left_fee_total"] == Decimal("20.00")
    assert result.results[0]["right_fee_total"] == Decimal("20.00")
    assert result.results[0]["left_net_total"] == Decimal("100.00")
    assert result.results[0]["right_net_total"] == Decimal("100.00")


def test_grouped_strategy_supports_bounded_partial_settlement_with_residuals() -> None:
    result = GroupedSubsetSumStrategy().execute(
        MatchingStrategyRequest(
            left_records=(
                {"id": "L1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            right_records=(
                {"id": "R1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R2", "amount": "20.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            mode="partial-settlement",
        )
    )

    assert result.results[0]["status"] == "matched"
    assert result.results[0]["reason_code"] == "PARTIAL_SETTLEMENT_PROPOSAL"
    assert result.results[0]["settled_amount"] == Decimal("80.00")
    assert result.results[0]["left_residual"] == Decimal("20.00")
    assert result.results[0]["right_residual"] == Decimal("0")


def test_grouped_strategy_applies_reviewed_request_budget_and_binds_it_to_digest() -> None:
    strategy = GroupedSubsetSumStrategy()
    base = MatchingStrategyRequest(
        left_records=(
            {"id": "L1", "amount": "100", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
        ),
        right_records=(
            {"id": "R1", "amount": "40", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            {"id": "R2", "amount": "30", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            {"id": "R3", "amount": "30", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
        ),
        mode="one-to-many",
    )
    bounded = replace(
        base,
        grouped_budget=GroupedMatchBudget(max_right_cardinality=2, max_search_evaluations=100),
    )

    result = strategy.execute(bounded)

    assert result.results[0]["status"] == "unmatched"
    assert result.input_digest != strategy.execute(base).input_digest


def test_grouped_strategy_rejects_unreviewed_or_mode_incompatible_budget() -> None:
    strategy = GroupedSubsetSumStrategy()
    request = MatchingStrategyRequest(left_records=(), right_records=(), mode="one-to-many")
    with pytest.raises(MatchingStrategyContractError, match="reviewed strategy ceiling"):
        strategy.execute(replace(request, grouped_budget=GroupedMatchBudget(max_right_cardinality=5)))
    with pytest.raises(MatchingStrategyContractError, match="cardinality floor"):
        strategy.execute(replace(request, grouped_budget=GroupedMatchBudget(max_right_cardinality=1)))


def test_non_grouped_strategy_does_not_ignore_grouped_budget(tmp_path: Path) -> None:
    strategy, _service, connection = _strategy(tmp_path)
    try:
        with pytest.raises(MatchingStrategyContractError, match="does not support grouped match budgets"):
            strategy.execute(
                replace(
                    _request(),
                    grouped_budget=GroupedMatchBudget(max_search_evaluations=1),
                )
            )
    finally:
        connection.close()


def test_grouped_strategy_supports_non_overlapping_portfolio_mode() -> None:
    result = GroupedSubsetSumStrategy().execute(
        MatchingStrategyRequest(
            left_records=(
                {"id": "L1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "L2", "amount": "50.00", "currency": "USD", "date": "2026-01-11", "partition": "AR"},
            ),
            right_records=(
                {"id": "R1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R2", "amount": "50.00", "currency": "USD", "date": "2026-01-11", "partition": "AR"},
            ),
            mode="portfolio",
        )
    )

    assert len(result.results) == 2
    assert result.exceptions == ()
    assert {item["left_record_ids"] for item in result.results} == {("L1",), ("L2",)}


def test_grouped_strategy_supports_explicit_partial_portfolio_mode() -> None:
    result = GroupedSubsetSumStrategy().execute(
        MatchingStrategyRequest(
            left_records=(
                {"id": "L1", "amount": "100", "currency": "USD", "date": "2026-01-01", "partition": "AR"},
                {"id": "L2", "amount": "40", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            right_records=(
                {"id": "R1", "amount": "75", "currency": "USD", "date": "2026-01-01", "partition": "AR"},
                {"id": "R2", "amount": "40", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            mode="portfolio",
            allow_partial_settlement=True,
            date_window_days=2,
        )
    )
    partial = next(item for item in result.results if item["left_record_ids"] == ("L1",))
    assert partial["reason_code"] == "GROUP_PORTFOLIO_PARTIAL_SETTLEMENT"
    assert partial["settled_amount"] == Decimal("75")
    assert partial["left_residual"] == Decimal("25")


def test_grouped_strategy_reports_ambiguity_for_equal_cost_candidates() -> None:
    strategy = GroupedSubsetSumStrategy()
    result = strategy.execute(
        MatchingStrategyRequest(
            left_records=({"id": "L1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},),
            right_records=(
                {"id": "R1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R3", "amount": "70.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
                {"id": "R4", "amount": "30.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            ),
            mode="one-to-many",
            amount_tolerance="0",
        )
    )

    assert result.results[0]["status"] == "ambiguous"
    assert result.results[0]["reason_code"] == "GROUP_MATCH_AMBIGUOUS"
    assert tuple(result.results[0]["ambiguous_candidate_sets"]) == (
        (("L1",), ("R1", "R2")),
        (("L1",), ("R3", "R4")),
    )
    assert result.exceptions == (
        {
            "reason_code": "GROUP_MATCH_AMBIGUOUS",
            "decision_digest": result.results[0]["decision_digest"],
        },
    )


def test_grouped_strategy_rejects_netting_without_fee_fields() -> None:
    strategy = GroupedSubsetSumStrategy()

    with pytest.raises(MatchingStrategyContractError, match="fee field names"):
        strategy.execute(
            MatchingStrategyRequest(
                left_records=(),
                right_records=(),
                mode="one-to-many",
                netting_mode="net",
                left_fee_field="",
                right_fee_field="fee",
            )
        )


def test_request_digest_covers_fee_and_netting_fields() -> None:
    base = _request(mode="one-to-many")
    netting = MatchingStrategyRequest(
        left_records=base.left_records,
        right_records=base.right_records,
        amount_tolerance=base.amount_tolerance,
        date_window_days=base.date_window_days,
        left_fee_field="fee",
        right_fee_field="fee",
        netting_mode="net",
        mode="one-to-many",
    )
    gross = _request(mode="one-to-many")
    assert request_digest(gross, "manifest") != request_digest(netting, "manifest")


def test_grouped_strategy_supports_fx_rates_and_target_currency() -> None:
    strategy = GroupedSubsetSumStrategy()
    request = MatchingStrategyRequest(
        left_records=(
            {"id": "L1", "amount": "60.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
            {"id": "L2", "amount": "40.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},
        ),
        right_records=(
            {"id": "R1", "amount": "200.00", "currency": "EUR", "date": "2026-01-10", "partition": "AR"},
        ),
        mode="many-to-one",
        target_currency="USD",
        fx_rates=(
            {
                "base_currency": "EUR",
                "quote_currency": "USD",
                "rate": "0.5",
                "rate_type": "spot",
                "source": "ECB",
                "effective_at": "2026-01-01",
            },
        ),
    )
    result = strategy.execute(request)
    assert result.results[0]["status"] == "matched"
    assert result.results[0]["currency"] == "USD"


def test_request_digest_includes_fx_rate_definitions() -> None:
    base = _request(mode="one-to-many")
    with_fx = MatchingStrategyRequest(
        left_records=base.left_records,
        right_records=base.right_records,
        amount_tolerance=base.amount_tolerance,
        date_window_days=base.date_window_days,
        mode="one-to-many",
        target_currency="USD",
        fx_rates=(
            {
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate": "1",
                "rate_type": "spot",
                "source": "MANUAL",
            },
        ),
    )
    no_fx = _request(mode="one-to-many")
    assert request_digest(with_fx, "manifest") != request_digest(no_fx, "manifest")


def test_grouped_strategy_rejects_cross_currency_target_without_fx_rates() -> None:
    strategy = GroupedSubsetSumStrategy()

    with pytest.raises(MatchingStrategyContractError, match="requires FX rate data"):
        strategy.execute(
            MatchingStrategyRequest(
                left_records=({"id": "L1", "amount": "100.00", "currency": "USD", "date": "2026-01-10", "partition": "AR"},),
                right_records=(
                    {"id": "R1", "amount": "80.00", "currency": "EUR", "date": "2026-01-10", "partition": "AR"},
                ),
                mode="one-to-many",
                target_currency="USD",
            )
        )
