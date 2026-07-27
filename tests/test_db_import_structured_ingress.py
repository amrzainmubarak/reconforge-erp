from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import reconforge.db.importers as importers
from reconforge.audit import list_audit_events
from reconforge.db import connect, run_migrations
from reconforge.db.exporter import DBBridgeError
from reconforge.io.structured import StructuredDocumentPolicy

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "schemas"
SAFE_ERROR = "Input JSON could not be parsed."


def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "reconforge.db"
    run_migrations(db_path)
    return db_path


def _account_source(tmp_path: Path, payload: bytes) -> Path:
    source = tmp_path / "account_reconciliations.json"
    source.write_bytes(payload)
    return source


def _control_source(tmp_path: Path, payload: bytes) -> Path:
    source = tmp_path / "control_tests.json"
    source.write_bytes(payload)
    return source


def _mutation_counts(db_path: Path) -> tuple[int, int, int, int]:
    connection = connect(db_path, require_exists=True)
    try:
        tables = (
            "workflow_objects",
            "legacy_import_records",
            "audit_events",
            "outbox_events",
        )
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        )
    finally:
        connection.close()


def _assert_account_rejected_without_mutation(
    tmp_path: Path,
    payload: bytes,
) -> None:
    db_path = _seed_db(tmp_path)
    source = _account_source(tmp_path, payload)
    before = _mutation_counts(db_path)

    with pytest.raises(DBBridgeError, match=f"^{SAFE_ERROR}$"):
        importers.import_account_reconciliations(db_path, source)

    assert _mutation_counts(db_path) == before


@pytest.mark.parametrize(
    "payload",
    [
        b'{"records":[],"records":[]}',
        b'{"records":[{"id":"AR-1","value":NaN}]}',
        b'{"records":[{"id":"\xff"}]}',
        b"",
    ],
    ids=["duplicate-key", "non-finite", "invalid-utf8", "empty"],
)
def test_hostile_json_is_generic_and_pre_mutation(tmp_path: Path, payload: bytes) -> None:
    _assert_account_rejected_without_mutation(tmp_path, payload)


def _small_policy(**overrides: int) -> StructuredDocumentPolicy:
    values = {
        "max_file_bytes": 4096,
        "max_nodes": 1000,
        "max_depth": 16,
        "max_collection_items": 100,
        "max_scalar_characters": 100,
        "max_yaml_aliases": 1,
    }
    values.update(overrides)
    return StructuredDocumentPolicy(**values)


@pytest.mark.parametrize(
    ("policy", "payload"),
    [
        (_small_policy(max_file_bytes=48), b'{"records":[{"id":"' + b"A" * 80 + b'"}]}'),
        (_small_policy(max_nodes=8), b'{"records":[{"id":"AR-1","a":1,"b":2,"c":3}]}'),
        (_small_policy(max_depth=3), b'{"records":[{"id":{"nested":"AR-1"}}]}'),
        (
            _small_policy(max_collection_items=2),
            b'{"records":[{"id":"AR-1"},{"id":"AR-2"},{"id":"AR-3"}]}',
        ),
        (_small_policy(max_scalar_characters=4), b'{"records":[{"id":"AR-LONG"}]}'),
    ],
    ids=["bytes", "nodes", "depth", "collection", "scalar"],
)
def test_named_resource_budgets_fail_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy: StructuredDocumentPolicy,
    payload: bytes,
) -> None:
    monkeypatch.setattr(importers, "LEGACY_DB_IMPORT_JSON_POLICY", policy)
    _assert_account_rejected_without_mutation(tmp_path, payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "account_reconciliations": [{"id": "AR-1"}],
            "records": [{"id": "AR-2"}],
        },
        {"metadata": "silently-empty-before-e064"},
        {"account_reconciliations": {"AR-1": {"status": "Draft"}}},
        [1],
    ],
    ids=["ambiguous-aliases", "invalid-envelope", "non-list-envelope", "non-object-record"],
)
def test_ambiguous_or_invalid_envelopes_fail_before_mutation(
    tmp_path: Path,
    payload: object,
) -> None:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    db_path = _seed_db(tmp_path)
    source = _account_source(tmp_path, encoded)
    before = _mutation_counts(db_path)

    with pytest.raises(DBBridgeError):
        importers.import_account_reconciliations(db_path, source)

    assert _mutation_counts(db_path) == before


@pytest.mark.parametrize(
    "payload",
    [
        [{"id": "AR-DIRECT", "status": "Draft"}],
        {"account_reconciliations": [{"id": "AR-PRIMARY"}]},
        {"reconciliations": [{"id": "AR-ALIAS"}]},
        {"records": [{"id": "AR-RECORDS"}]},
        {"items": [{"id": "AR-ITEMS"}]},
        {"AR-MAPPED": {"status": "Reviewed"}},
        {},
    ],
    ids=["direct", "primary", "reconciliations", "records", "items", "keyed-map", "empty"],
)
def test_account_import_preserves_documented_legacy_shapes(
    tmp_path: Path,
    payload: object,
) -> None:
    db_path = _seed_db(tmp_path)
    source = _account_source(tmp_path, json.dumps(payload).encode("utf-8"))

    result = importers.import_account_reconciliations(db_path, source)

    expected = 0 if payload == {} else 1
    assert result.imported_count == expected
    assert _mutation_counts(db_path)[1] == expected


def test_control_import_records_parsed_digest_and_ingress_profile(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    raw = b'{"tests":[{"test_id":"CT-INGRESS","status":"Complete"}]}'
    source = _control_source(tmp_path, raw)

    result = importers.import_control_tests(db_path, source)

    assert result.imported_count == 1
    expected_digest = hashlib.sha256(raw).hexdigest()
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute(
            "SELECT source_checksum_sha256, summary_json FROM legacy_import_records",
        ).fetchone()
        events = list_audit_events(connection)
    finally:
        connection.close()
    assert row["source_checksum_sha256"] == expected_digest
    summary = json.loads(str(row["summary_json"]))
    assert summary["ingress_profile"] == importers.LEGACY_DB_IMPORT_JSON_PROFILE
    assert summary["source_size_bytes"] == len(raw)
    imported_event = next(event for event in events if event.action == "legacy_control_tests_imported")
    assert imported_event.metadata["source_checksum_sha256"] == expected_digest
    assert imported_event.metadata["ingress_profile"] == importers.LEGACY_DB_IMPORT_JSON_PROFILE
    assert imported_event.metadata["source_size_bytes"] == len(raw)


def test_json_change_during_validation_fails_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = _seed_db(tmp_path)
    source = _account_source(tmp_path, b'{"records":[{"id":"AR-BEFORE"}]}')
    real_reader = importers.read_json_document

    def mutate_after_parse(path: Path, **kwargs: object) -> object:
        payload = real_reader(path, **kwargs)
        source.write_bytes(b'{"records":[{"id":"AR-AFTER"}]}')
        return payload

    monkeypatch.setattr(importers, "read_json_document", mutate_after_parse)
    before = _mutation_counts(db_path)

    with pytest.raises(DBBridgeError, match=f"^{SAFE_ERROR}$"):
        importers.import_account_reconciliations(db_path, source)

    assert _mutation_counts(db_path) == before


def test_reparse_predicate_fails_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = _seed_db(tmp_path)
    source = _account_source(tmp_path, b'{"records":[{"id":"AR-1"}]}')
    monkeypatch.setattr(importers, "_path_is_reparse", lambda _path: True)
    before = _mutation_counts(db_path)

    with pytest.raises(DBBridgeError, match=f"^{SAFE_ERROR}$"):
        importers.import_account_reconciliations(db_path, source)

    assert _mutation_counts(db_path) == before


def test_published_import_schemas_match_runtime_shapes() -> None:
    cases = [
        (
            "database_account_reconciliations_import.schema.json",
            {"account_reconciliations": [{"id": "AR-1"}]},
            {"account_reconciliations": [], "records": []},
        ),
        (
            "database_control_tests_import.schema.json",
            {"tests": [{"test_id": "CT-1"}]},
            {"control_tests": [], "items": []},
        ),
    ]
    for filename, valid, ambiguous in cases:
        schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(valid)
        assert list(validator.iter_errors(ambiguous))


def test_importer_has_no_direct_json_file_parser_and_exact_profile() -> None:
    source_path = ROOT / "reconforge" / "db" / "importers.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "json"
            and function.attr in {"load", "loads"}
        ):
            forbidden.append(f"json.{function.attr}")
        if isinstance(function, ast.Attribute) and function.attr == "read_text":
            forbidden.append("read_text")

    assert forbidden == []
    assert source.count("_read_json(source_path)") == 2
    assert importers.LEGACY_DB_IMPORT_JSON_PROFILE == "database-legacy-import-json-ingress-v1"
    assert StructuredDocumentPolicy(
        max_file_bytes=16 * 1024 * 1024,
        max_nodes=500_000,
        max_depth=32,
        max_collection_items=50_000,
        max_scalar_characters=1024 * 1024,
        max_yaml_aliases=1,
    ) == importers.LEGACY_DB_IMPORT_JSON_POLICY
