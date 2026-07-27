from __future__ import annotations

import ast
import json
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)
from reconforge.io import persisted as persisted_module
from reconforge.io.persisted import (
    POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY,
    POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_PROFILE,
    POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY,
    POSTGRES_RECONCILIATION_EVIDENCE_JSON_PROFILE,
    POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY,
    POSTGRES_RECONCILIATION_LINEAGE_JSON_PROFILE,
    POSTGRES_RECONCILIATION_OBJECT_SCHEMA,
    POSTGRES_RECONCILIATION_RULE_JSON_POLICY,
    POSTGRES_RECONCILIATION_RULE_JSON_PROFILE,
    PersistedJsonError,
    PersistedJsonObjectDocument,
    decode_postgres_reconciliation_attributes,
    decode_postgres_reconciliation_evidence,
    decode_postgres_reconciliation_lineage,
    decode_postgres_reconciliation_rule,
    encode_postgres_reconciliation_attributes,
    encode_postgres_reconciliation_evidence,
    encode_postgres_reconciliation_lineage,
    encode_postgres_reconciliation_rule,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
)

ROOT = Path(__file__).resolve().parents[1]
Decoder = Callable[[object], PersistedJsonObjectDocument]
Encoder = Callable[[Mapping[str, Any] | None], PersistedJsonObjectDocument]

CONTRACTS: tuple[tuple[str, Decoder, Encoder, str], ...] = (
    (
        "rule",
        decode_postgres_reconciliation_rule,
        encode_postgres_reconciliation_rule,
        POSTGRES_RECONCILIATION_RULE_JSON_PROFILE,
    ),
    (
        "attributes",
        decode_postgres_reconciliation_attributes,
        encode_postgres_reconciliation_attributes,
        POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_PROFILE,
    ),
    (
        "lineage",
        decode_postgres_reconciliation_lineage,
        encode_postgres_reconciliation_lineage,
        POSTGRES_RECONCILIATION_LINEAGE_JSON_PROFILE,
    ),
    (
        "evidence",
        decode_postgres_reconciliation_evidence,
        encode_postgres_reconciliation_evidence,
        POSTGRES_RECONCILIATION_EVIDENCE_JSON_PROFILE,
    ),
)


@pytest.mark.parametrize(("field_name", "decoder", "encoder", "profile"), CONTRACTS)
def test_reconciliation_persisted_objects_round_trip_canonically_and_validate_schema(
    field_name: str,
    decoder: Decoder,
    encoder: Encoder,
    profile: str,
) -> None:
    payload = {"amount": "10.250", "display_ratio": 1.25, "nested": {"accepted": True}}
    expected = '{"amount":"10.250","display_ratio":1.25,"nested":{"accepted":true}}'

    produced = encoder(payload)
    decoded = decoder('{"nested":{"accepted":true},"display_ratio":1.25,"amount":"10.250"}')
    mapping = decoder(payload)
    schema = json.loads((ROOT / "docs/schemas/postgres_reconciliation_object.schema.json").read_text("utf-8"))

    assert produced.text == expected, field_name
    assert decoded.payload == payload
    assert mapping.text == expected
    assert decoded.profile_id == profile
    assert decoded.schema_id == POSTGRES_RECONCILIATION_OBJECT_SCHEMA
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decoded.payload)


@pytest.mark.parametrize(("_field_name", "decoder", "_encoder", "_profile"), CONTRACTS)
@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"id":"one","id":"two"}', "persisted_json_duplicate_key"),
        ('{"value":NaN}', "persisted_document_non_finite_number"),
        ('{"value":Infinity}', "persisted_document_non_finite_number"),
        ('[]', "persisted_json_object_required"),
    ],
)
def test_reconciliation_persisted_objects_reject_ambiguous_or_invalid_stored_values(
    _field_name: str,
    decoder: Decoder,
    _encoder: Encoder,
    _profile: str,
    text: str,
    code: str,
) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decoder(text)
    assert captured.value.code == code


def test_reconciliation_profiles_enforce_field_specific_runtime_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_RULE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )

    for _, decoder, encoder, _ in CONTRACTS:
        with pytest.raises(PersistedJsonError):
            encoder({"value": "exceeds-budget"})
        with pytest.raises(PersistedJsonError):
            decoder('{"nested":{"value":"x"}}')


def test_repository_producers_reject_before_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoDatabaseAccess:
        def execute(self, *_: object) -> Any:
            raise AssertionError("database access must not occur")

    repository = PostgresReconciliationRepository(_NoDatabaseAccess())
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_RULE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=8),
    )
    with pytest.raises(PostgresReconciliationValidationError, match="rule must be a bounded JSON object"):
        repository.create_run(
            tenant_id="tenant_a",
            run_id="run-a",
            name="bounded",
            left_source="left",
            right_source="right",
            algorithm_version="v1",
            rule={"value": "too-large"},
            input_hash="hash-a",
            actor_id="actor-a",
        )

    cases = (
        ("attributes", "register_input", {"side": "Left", "source_id": "left-a", "record_hash": "hash-a"}),
        (
            "lineage",
            "append_result",
            {
                "left_id": "left-a",
                "match_type": "exact",
                "confidence": "1",
                "explanation": "exact",
                "status": "Matched",
            },
        ),
        (
            "evidence",
            "append_exception",
            {
                "exception_type": "quality",
                "source_side": "Left",
                "source_id": "left-a",
                "title": "quality",
                "explanation": "quality",
                "severity": "High",
                "risk_score": "1",
                "reason_code": "QUALITY",
            },
        ),
    )
    for field_name, method_name, values in cases:
        monkeypatch.setattr(
            persisted_module,
            f"POSTGRES_RECONCILIATION_{field_name.upper()}_JSON_POLICY",
            StructuredDocumentPolicy(max_file_bytes=8),
        )
        with pytest.raises(PostgresReconciliationValidationError, match=f"{field_name} must be a bounded JSON object"):
            getattr(repository, method_name)(
                tenant_id="tenant_a",
                run_id="run-a",
                **values,
                **{field_name: {"value": "too-large"}},
            )

    with pytest.raises(PostgresReconciliationValidationError, match="lineage must be a bounded JSON object"):
        repository.append_partition(
            tenant_id="tenant_a",
            run_id="run-a",
            partition_key="partition-a",
            input_count=1,
            worker_id="worker-a",
            results=(
                {
                    "left_id": "left-a",
                    "match_type": "exact",
                    "confidence": "1",
                    "explanation": "exact",
                    "status": "Matched",
                    "lineage": {"value": "too-large"},
                },
            ),
        )


def test_repository_consumers_return_objects_and_refuse_corruption_without_sentinels() -> None:
    record = PostgresReconciliationRepository._record(
        {
            "rule_json": '{"b":2,"a":1}',
            "attributes_json": {"source_id": "left-a"},
            "lineage_json": '{"candidate_count":1}',
            "evidence_json": {"source": "left-a"},
        },
        (),
    )
    assert record == {
        "rule_json": {"a": 1, "b": 2},
        "attributes_json": {"source_id": "left-a"},
        "lineage_json": {"candidate_count": 1},
        "evidence_json": {"source": "left-a"},
    }

    for key in ("rule_json", "attributes_json", "lineage_json", "evidence_json"):
        with pytest.raises(PostgresReconciliationIntegrityError, match="Stored .* is invalid"):
            PostgresReconciliationRepository._record({key: "[]"}, ())


def test_rule_canonicalization_preserves_established_fingerprint_bytes() -> None:
    rule = {"date_window_days": 2, "amount_tolerance": "0.01"}
    historical = json.dumps(rule, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    mapping_text = PostgresReconciliationRepository._canonical_json_text(rule, "rule")
    jsonb_text = PostgresReconciliationRepository._canonical_json_text(
        '{"date_window_days": 2, "amount_tolerance": "0.01"}',
        "rule",
    )

    assert mapping_text == historical == jsonb_text
    assert PostgresReconciliationRepository._hash_payload({"rule": mapping_text}) == (
        PostgresReconciliationRepository._hash_payload({"rule": historical})
    )


class _Row:
    def __init__(self, value: Mapping[str, object]) -> None:
        self.value = value

    def fetchone(self) -> Mapping[str, object]:
        return self.value


class _CorruptClaimConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.executed: list[str] = []

    @contextmanager
    def transaction(self) -> Any:
        yield self
        self.commits += 1

    def close(self) -> None:
        return None

    def execute(self, sql: str, _: tuple[object, ...]) -> _Row:
        self.executed.append(" ".join(sql.split()).lower())
        return _Row({"rule_json": "[]"})


class _CorruptClaimFactory:
    def __init__(self, connection: _CorruptClaimConnection) -> None:
        self.connection = connection

    def connect(self) -> _CorruptClaimConnection:
        return self.connection


def test_corrupt_rule_rolls_back_before_claim_mutation_or_matcher_invocation() -> None:
    connection = _CorruptClaimConnection()
    matched: list[str] = []
    worker = PostgresReconciliationWorker(
        _CorruptClaimFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: matched.append("called"),  # type: ignore[arg-type]
        settings=PostgresReconciliationWorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
    )

    with pytest.raises(PostgresReconciliationWorkerError, match="Unable to persist reconciliation execution failure"):
        worker.process_run(tenant_id="tenant_a", run_id="run-a")

    assert matched == []
    assert connection.commits == 0
    assert all(not statement.startswith("update reconforge.reconciliation_runs") for statement in connection.executed)


def test_matcher_worker_helpers_share_bounded_consumers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=8),
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="Stored attributes_json is invalid"):
        LocalDeterministicMatcherAdapter._json_object({"value": "too-large"}, "attributes_json")

    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_RECONCILIATION_RULE_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=8),
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="Stored reconciliation rule is invalid"):
        PostgresReconciliationWorker._rule_mapping({"rule_json": {"value": "too-large"}})


def test_reconciliation_jsonb_call_sites_are_governed_without_direct_decoders() -> None:
    repository_path = ROOT / "reconforge/infrastructure/postgres_reconciliation.py"
    worker_path = ROOT / "reconforge/workers/postgres_reconciliation.py"
    for path in (repository_path, worker_path):
        source = path.read_text("utf-8")
        tree = ast.parse(source, filename=str(path))
        direct = [
            call.lineno
            for call in ast.walk(tree)
            if isinstance(call, ast.Call) and ast.unparse(call.func) == "json.loads"
        ]
        assert direct == []

    source = repository_path.read_text("utf-8")
    tree = ast.parse(source, filename=str(repository_path))
    expected = {"create_run": "rule", "register_input": "attributes", "append_result": "lineage", "append_exception": "evidence"}
    governed: dict[str, str] = {}
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        if function.name not in expected:
            continue
        arguments = [
            call.args[1].value
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func) == "self._json_text"
            and len(call.args) == 2
            and isinstance(call.args[1], ast.Constant)
            and isinstance(call.args[1].value, str)
        ]
        assert arguments == [expected[function.name]]
        governed[function.name] = arguments[0]
    assert governed == expected


def test_reconciliation_json_profiles_have_explicit_compatible_ceilings() -> None:
    assert POSTGRES_RECONCILIATION_RULE_JSON_POLICY.max_file_bytes == 4 * 1024 * 1024
    assert POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY.max_file_bytes == 100_000
    assert POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY.max_file_bytes == 4 * 1024 * 1024
    assert POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY.max_file_bytes == 4 * 1024 * 1024
    for policy in (
        POSTGRES_RECONCILIATION_RULE_JSON_POLICY,
        POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY,
        POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY,
        POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY,
    ):
        assert policy.max_nodes == 100_000
        assert policy.max_depth == 32
        assert policy.max_collection_items == 25_000
    assert POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY.max_scalar_characters == 100_000
    assert POSTGRES_RECONCILIATION_RULE_JSON_POLICY.max_scalar_characters == 256 * 1024
