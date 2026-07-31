from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.db.connection import connect
from reconforge.db.migrations import run_migrations
from reconforge.io import persisted as persisted_module
from reconforge.io.persisted import (
    SQLITE_MATCHING_RULE_JSON_POLICY,
    SQLITE_MATCHING_RULE_JSON_PROFILE,
    SQLITE_MATCHING_RULE_SCHEMA,
    PersistedJsonError,
    decode_sqlite_matching_rule,
    encode_sqlite_matching_rule,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.platform.common import PlatformError
from reconforge.platform.matching import MatchingService
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY
from reconforge.utils.money import LEGACY_FINANCIAL_INPUT_POLICY, STRICT_FINANCIAL_INPUT_POLICY

ROOT = Path(__file__).resolve().parents[1]


def _sources(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("id,amount,reference,date\nL-1,10.50,INV-1,2026-07-26\n", encoding="utf-8")
    right.write_text("id,amount,reference,date\nR-1,10.50,INV-1,2026-07-26\n", encoding="utf-8")
    return left, right


def _counts(connection: object) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])  # type: ignore[attr-defined]
        for table in ("match_jobs", "match_rules", "match_results", "audit_events", "outbox_events")
    }


def test_sqlite_matching_rule_round_trip_preserves_historical_canonical_text_and_schema() -> None:
    rule = {
        "amount_tolerance": "0.01",
        "date_window_days": 2,
        "financial_input_policy": STRICT_FINANCIAL_INPUT_POLICY,
    }
    historical = json.dumps(rule, sort_keys=True)

    produced = encode_sqlite_matching_rule(rule)
    decoded = decode_sqlite_matching_rule(
        '{"financial_input_policy":"strict-financial-input-v2","date_window_days":2,"amount_tolerance":"0.01"}'
    )
    mapping = decode_sqlite_matching_rule(rule)
    schema = json.loads((ROOT / "docs/schemas/sqlite_matching_rule.schema.json").read_text("utf-8"))

    assert produced.text == historical == decoded.text == mapping.text
    assert decoded.payload == rule
    assert decoded.profile_id == SQLITE_MATCHING_RULE_JSON_PROFILE
    assert decoded.schema_id == SQLITE_MATCHING_RULE_SCHEMA
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decoded.payload)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"policy":"one","policy":"two"}', "persisted_json_duplicate_key"),
        ('{"value":NaN}', "persisted_document_non_finite_number"),
        ('{"value":Infinity}', "persisted_document_non_finite_number"),
        ('[]', "persisted_json_object_required"),
    ],
)
def test_sqlite_matching_rule_rejects_ambiguous_or_invalid_stored_values(text: str, code: str) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decode_sqlite_matching_rule(text)
    assert captured.value.code == code


def test_sqlite_matching_rule_reads_finite_historical_numbers_but_new_producer_rejects_float() -> None:
    historical = decode_sqlite_matching_rule('{"amount_tolerance": 0.1}')
    assert historical.payload == {"amount_tolerance": 0.1}
    assert historical.text == '{"amount_tolerance": 0.1}'

    with pytest.raises(PersistedJsonError) as captured:
        encode_sqlite_matching_rule({"amount_tolerance": 0.1})
    assert captured.value.code == "persisted_json_fractional_number_forbidden"


def test_sqlite_matching_rule_rejects_cycles_and_runtime_resource_excess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(PersistedJsonError) as captured:
        encode_sqlite_matching_rule(cyclic)
    assert captured.value.code == "persisted_json_cycle_forbidden"

    monkeypatch.setattr(
        persisted_module,
        "SQLITE_MATCHING_RULE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )
    with pytest.raises(PersistedJsonError):
        encode_sqlite_matching_rule({"value": "exceeds-budget"})
    with pytest.raises(PersistedJsonError):
        decode_sqlite_matching_rule('{"nested":{"value":"x"}}')


def test_matching_service_writes_one_rule_text_to_both_tables_and_replays_policies(tmp_path: Path) -> None:
    database = tmp_path / "matching-rule.db"
    left, right = _sources(tmp_path)
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        service = MatchingService(connection)
        first = service.run(
            left_path=left,
            right_path=right,
            idempotency_key="bounded-rule-1",
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
            amount_tolerance="0.01",
        )
        repeated = service.run(
            left_path=left,
            right_path=right,
            idempotency_key="bounded-rule-1",
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
            amount_tolerance="0.01",
        )
        job_rule = str(connection.execute("SELECT rule_json FROM match_jobs WHERE id = ?", (first.job_id,)).fetchone()["rule_json"])
        named_rule = str(connection.execute("SELECT rule_json FROM match_rules WHERE job_id = ?", (first.job_id,)).fetchone()["rule_json"])
        status = service.job_status(first.job_id)
        listed = service.list_jobs()
    finally:
        connection.close()

    assert first == repeated
    assert job_rule == named_rule == decode_sqlite_matching_rule(job_rule).text
    assert '"amount_tolerance": "0.01"' in job_rule
    assert decode_sqlite_matching_rule(job_rule).payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert decode_sqlite_matching_rule(job_rule).payload["record_identity_policy"] == RECORD_IDENTITY_POLICY
    assert status["rule_json"] == job_rule
    assert listed[0]["rule_json"] == job_rule


def test_corrupt_idempotent_rule_fails_before_new_business_audit_or_outbox_effect(tmp_path: Path) -> None:
    database = tmp_path / "corrupt-replay.db"
    left, right = _sources(tmp_path)
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        service = MatchingService(connection)
        first = service.run(left_path=left, right_path=right, idempotency_key="corrupt-rule-1")
        connection.execute(
            "UPDATE match_jobs SET rule_json = ? WHERE id = ?",
            ('{"financial_input_policy":"one","financial_input_policy":"two"}', first.job_id),
        )
        connection.commit()
        before = _counts(connection)

        with pytest.raises(PlatformError, match="Existing idempotent match rule is invalid") as captured:
            service.run(left_path=left, right_path=right, idempotency_key="corrupt-rule-1")

        after = _counts(connection)
    finally:
        connection.close()

    assert before == after
    assert "financial_input_policy" not in str(captured.value)


def test_public_matching_job_readers_refuse_corrupt_rules_without_sentinels(tmp_path: Path) -> None:
    database = tmp_path / "corrupt-public-read.db"
    left, right = _sources(tmp_path)
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(left_path=left, right_path=right)
        connection.execute("UPDATE match_jobs SET rule_json = '[]' WHERE id = ?", (result.job_id,))
        connection.commit()

        with pytest.raises(PlatformError, match="Stored matching rule is invalid"):
            service.job_status(result.job_id)
        with pytest.raises(PlatformError, match="Stored matching rule is invalid"):
            service.list_jobs()
    finally:
        connection.close()


def test_rule_budget_rejection_occurs_before_transaction_or_persisted_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "producer-budget.db"
    left, right = _sources(tmp_path)
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        service = MatchingService(connection)
        before = _counts(connection)
        monkeypatch.setattr(
            persisted_module,
            "SQLITE_MATCHING_RULE_JSON_POLICY",
            StructuredDocumentPolicy(max_file_bytes=64),
        )

        with pytest.raises(PlatformError, match="Matching rule is invalid"):
            service.run(left_path=left, right_path=right, idempotency_key="oversized-rule")

        after = _counts(connection)
        in_transaction = connection.in_transaction
    finally:
        connection.close()

    assert before == after
    assert in_transaction is False


def test_missing_policy_historical_rule_retains_legacy_replay_defaults(tmp_path: Path) -> None:
    database = tmp_path / "legacy-rule.db"
    left, right = _sources(tmp_path)
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        service = MatchingService(connection)
        first = service.run(left_path=left, right_path=right, idempotency_key="legacy-rule-1")
        connection.execute("UPDATE match_jobs SET rule_json = '{}' WHERE id = ?", (first.job_id,))
        connection.commit()

        repeated = service.run(
            left_path=left,
            right_path=right,
            idempotency_key="legacy-rule-1",
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
    finally:
        connection.close()

    assert repeated.job_id == first.job_id
    assert repeated.financial_input_policy == LEGACY_FINANCIAL_INPUT_POLICY


def test_matching_rule_call_sites_are_governed_without_direct_decoder() -> None:
    path = ROOT / "reconforge/infrastructure/sqlite_matching.py"
    source = path.read_text("utf-8")
    tree = ast.parse(source, filename=str(path))
    direct = [
        call.lineno
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and ast.unparse(call.func) == "json.loads"
    ]
    assert direct == []

    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_run_records")
    calls = [
        (ast.unparse(call.func), call.lineno)
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
    ]
    producer_line = next(line for name, line in calls if name == "self._matching_rule_document")
    begin_line = next(
        line
        for name, line in calls
        if name == "self.connection.execute"
        and "BEGIN IMMEDIATE" in (ast.get_source_segment(source, next(call for call in ast.walk(function) if isinstance(call, ast.Call) and call.lineno == line)) or "")
    )
    assert producer_line < begin_line
    assert source.count("json.dumps(rule, sort_keys=True)") == 0
    assert source.count("rule_json,") >= 3


def test_sqlite_matching_rule_policy_has_explicit_resource_ceilings() -> None:
    assert SQLITE_MATCHING_RULE_JSON_POLICY.max_file_bytes == 4 * 1024 * 1024
    assert SQLITE_MATCHING_RULE_JSON_POLICY.max_nodes == 100_000
    assert SQLITE_MATCHING_RULE_JSON_POLICY.max_depth == 32
    assert SQLITE_MATCHING_RULE_JSON_POLICY.max_collection_items == 25_000
    assert SQLITE_MATCHING_RULE_JSON_POLICY.max_scalar_characters == 256 * 1024
