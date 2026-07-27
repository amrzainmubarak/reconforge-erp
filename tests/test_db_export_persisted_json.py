from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from reconforge.audit import append_audit_event
from reconforge.db import connect, run_migrations
from reconforge.db.exporter import (
    EXPORT_JSON_FIELDS,
    SELECT_QUERIES,
    DBBridgeError,
    export_database,
)
from reconforge.domain.repositories import WorkspaceRepository
from reconforge.io import persisted as persisted_module
from reconforge.io.persisted import (
    SQLITE_LEGACY_IMPORT_SUMMARY_JSON_POLICY,
    SQLITE_LEGACY_IMPORT_SUMMARY_JSON_PROFILE,
    SQLITE_LEGACY_IMPORT_SUMMARY_SCHEMA,
    SQLITE_MATCHING_LINEAGE_JSON_POLICY,
    SQLITE_MATCHING_LINEAGE_JSON_PROFILE,
    SQLITE_MATCHING_LINEAGE_SCHEMA,
    PersistedJsonError,
    decode_sqlite_legacy_import_summary,
    decode_sqlite_matching_lineage,
    encode_sqlite_legacy_import_summary,
    encode_sqlite_matching_lineage,
)
from reconforge.io.structured import StructuredDocumentPolicy

ROOT = Path(__file__).resolve().parents[1]
_CORRUPT = '{"duplicate":1,"duplicate":2}'


def _seed_export_rows(tmp_path: Path) -> Path:
    database = tmp_path / "export-json.db"
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        workspace = WorkspaceRepository(connection).create(name="Export JSON Workspace")
        append_audit_event(
            connection,
            actor_label="tester",
            object_type="fixture",
            object_id="export-json",
            action="seeded",
            metadata={"synthetic": True},
        )
        connection.execute(
            """
            INSERT INTO legacy_import_records (
                id, source_type, object_type, object_id, status, source_path,
                source_checksum_sha256, summary_json, imported_at
            ) VALUES ('LEG-1', 'review', 'exception', 'EX-1', 'Open', 'review.json', ?, ?, ?)
            """,
            ("a" * 64, '{"count":1,"label":"caf\\u00e9"}', "2026-07-27T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO match_jobs (
                id, workspace_id, name, left_source, right_source, status,
                rule_json, created_by, created_at
            ) VALUES ('JOB-1', ?, 'Export', 'left.csv', 'right.csv', 'Completed', ?, 'tester', ?)
            """,
            (workspace.id, '{"amount_tolerance": "0.01"}', "2026-07-27T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO match_rules (id, job_id, rule_name, rule_json, created_at)
            VALUES ('RULE-1', 'JOB-1', 'primary', ?, ?)
            """,
            ('{"amount_tolerance": "0.01"}', "2026-07-27T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO match_results (
                id, job_id, left_id, right_id, match_type, confidence, explanation,
                amount_difference, amount_difference_decimal, date_difference_days,
                status, reason_code, lineage_json, created_at
            ) VALUES ('RESULT-1', 'JOB-1', 'L-1', 'R-1', 'Exact', 1, 'Exact', 0,
                      '0', 0, 'Matched', '', ?, ?)
            """,
            ('{"candidate_count":1,"label":"café"}', "2026-07-27T00:00:00Z"),
        )
        connection.commit()
    finally:
        connection.close()
    return database


def test_db_export_profile_schemas_and_historical_canonical_bytes() -> None:
    summary = {"label": "café", "count": 1, "ratio": 1.25}
    lineage = {"label": "café", "candidate_count": 1, "score": 1.0}

    encoded_summary = encode_sqlite_legacy_import_summary(summary)
    encoded_lineage = encode_sqlite_matching_lineage(lineage)
    decoded_summary = decode_sqlite_legacy_import_summary(encoded_summary.text)
    decoded_lineage = decode_sqlite_matching_lineage(encoded_lineage.text)

    assert encoded_summary.text == '{"count":1,"label":"caf\\u00e9","ratio":1.25}'
    assert encoded_lineage.text == '{"candidate_count":1,"label":"café","score":1.0}'
    assert decoded_summary.payload == summary
    assert decoded_lineage.payload == lineage
    assert decoded_summary.profile_id == SQLITE_LEGACY_IMPORT_SUMMARY_JSON_PROFILE
    assert decoded_summary.schema_id == SQLITE_LEGACY_IMPORT_SUMMARY_SCHEMA
    assert decoded_lineage.profile_id == SQLITE_MATCHING_LINEAGE_JSON_PROFILE
    assert decoded_lineage.schema_id == SQLITE_MATCHING_LINEAGE_SCHEMA

    for filename, payload in (
        ("sqlite_legacy_import_summary.schema.json", decoded_summary.payload),
        ("sqlite_matching_lineage.schema.json", decoded_lineage.payload),
    ):
        schema = json.loads((ROOT / "docs/schemas" / filename).read_text("utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)


@pytest.mark.parametrize(
    ("decoder", "text", "code"),
    [
        (decode_sqlite_legacy_import_summary, _CORRUPT, "persisted_json_duplicate_key"),
        (decode_sqlite_matching_lineage, _CORRUPT, "persisted_json_duplicate_key"),
        (decode_sqlite_legacy_import_summary, "[]", "persisted_json_object_required"),
        (decode_sqlite_matching_lineage, '{"value":NaN}', "persisted_document_non_finite_number"),
    ],
)
def test_db_export_profiles_reject_ambiguous_or_invalid_values(
    decoder: Callable[[object], object],
    text: str,
    code: str,
) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decoder(text)
    assert captured.value.code == code


def test_db_export_profiles_reject_cycles_and_runtime_resource_excess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(PersistedJsonError, match="persisted_json_cycle_forbidden"):
        encode_sqlite_matching_lineage(cyclic)

    monkeypatch.setattr(
        persisted_module,
        "SQLITE_LEGACY_IMPORT_SUMMARY_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )
    with pytest.raises(PersistedJsonError):
        encode_sqlite_legacy_import_summary({"value": "exceeds-budget"})
    with pytest.raises(PersistedJsonError):
        decode_sqlite_legacy_import_summary('{"nested":{"value":"x"}}')


def test_export_json_inventory_exactly_covers_exported_suffix_columns(tmp_path: Path) -> None:
    database = _seed_export_rows(tmp_path)
    connection = connect(database, require_exists=True)
    try:
        exported_json_fields: set[tuple[str, str]] = set()
        for table in SELECT_QUERIES:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists is None:
                continue
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall():
                column = str(row["name"])
                if column.endswith("_json"):
                    exported_json_fields.add((table, column))
    finally:
        connection.close()

    assert exported_json_fields == set(EXPORT_JSON_FIELDS)
    with pytest.raises(TypeError):
        cast(dict[tuple[str, str], object], EXPORT_JSON_FIELDS)[("unexpected", "field_json")] = object()


def test_valid_export_preserves_each_existing_public_field_shape(tmp_path: Path) -> None:
    database = _seed_export_rows(tmp_path)
    result = export_database(database, tmp_path / "export")
    audit = json.loads((result.output_dir / "audit_events.json").read_text("utf-8"))
    legacy = json.loads((result.output_dir / "legacy_imports.json").read_text("utf-8"))
    finance = json.loads((result.output_dir / "finance_workflows.json").read_text("utf-8"))

    assert isinstance(audit["audit_events"][0]["metadata"], dict)
    assert "metadata_json" not in audit["audit_events"][0]
    assert legacy["legacy_import_records"][0]["summary"] == {"count": 1, "label": "café"}
    assert "summary_json" not in legacy["legacy_import_records"][0]
    assert finance["match_jobs"][0]["rule"] == {"amount_tolerance": "0.01"}
    assert finance["match_rules"][0]["rule"] == {"amount_tolerance": "0.01"}
    assert finance["match_results"][0]["lineage_json"] == '{"candidate_count":1,"label":"café"}'


@pytest.mark.parametrize(
    ("table", "column"),
    sorted(EXPORT_JSON_FIELDS),
)
def test_corrupt_exported_json_refuses_before_output_directory_or_audit_effect(
    tmp_path: Path,
    table: str,
    column: str,
) -> None:
    database = _seed_export_rows(tmp_path)
    connection = connect(database, require_exists=True)
    try:
        if table == "audit_events":
            connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute(f"UPDATE {table} SET {column} = ?", (_CORRUPT,))
        connection.commit()
        before_count = int(
            connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        )
    finally:
        connection.close()

    output = tmp_path / "rejected-export"
    with pytest.raises(DBBridgeError, match="Unable to export local database records"):
        export_database(database, output)

    assert not output.exists()
    connection = connect(database, require_exists=True)
    try:
        after_count = int(
            connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        )
    finally:
        connection.close()
    assert after_count == before_count


def test_non_text_exported_json_is_rejected_without_touching_existing_destination(
    tmp_path: Path,
) -> None:
    database = _seed_export_rows(tmp_path)
    connection = connect(database, require_exists=True)
    try:
        connection.execute(
            "UPDATE legacy_import_records SET summary_json = ?",
            (b'{"unexpected":"blob"}',),
        )
        connection.commit()
    finally:
        connection.close()

    output = tmp_path / "existing-export"
    output.mkdir()
    marker = output / "operator-owned.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(DBBridgeError, match="Unable to export local database records"):
        export_database(database, output)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert list(output.glob("*.json")) == []


def test_exporter_has_no_direct_json_decoder_and_profiles_have_explicit_limits() -> None:
    path = ROOT / "reconforge/db/exporter.py"
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    direct = [
        call.lineno
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and ast.unparse(call.func) in {"json.load", "json.loads"}
    ]
    assert direct == []

    for policy in (
        SQLITE_LEGACY_IMPORT_SUMMARY_JSON_POLICY,
        SQLITE_MATCHING_LINEAGE_JSON_POLICY,
    ):
        assert policy.max_file_bytes == 4 * 1024 * 1024
        assert policy.max_nodes == 100_000
        assert policy.max_depth == 32
        assert policy.max_collection_items == 25_000
        assert policy.max_scalar_characters == 256 * 1024
