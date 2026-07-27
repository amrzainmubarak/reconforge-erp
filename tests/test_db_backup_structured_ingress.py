from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import reconforge.db.backup as backup_module
from reconforge.db import run_migrations
from reconforge.db.backup import create_backup, restore_backup, verify_backup
from reconforge.db.exporter import DBBridgeError, checksum_file
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy


def _backup_document() -> dict[str, Any]:
    schema_version = backup_module.MIGRATIONS[-1].version
    return {
        "backup_format_version": 1,
        "created_at": "2026-07-26T00:00:00Z",
        "schema_version": schema_version,
        "latest_supported_schema_version": schema_version,
        "privacy_warning": backup_module.BACKUP_WARNING,
        "restore_sensitive_material": "Includes local credential verifier fields needed for restore.",
        "excluded_tables": ["api_sessions"],
        "tables": {},
    }


def _write_bundle(
    root: Path,
    *,
    backup: dict[str, Any] | None = None,
    backup_bytes: bytes | None = None,
    mutate_manifest: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, Path]:
    root.mkdir()
    backup_path = root / "backup.json"
    if backup_bytes is None:
        backup_bytes = (
            json.dumps(backup or _backup_document(), indent=2, sort_keys=True, ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
    backup_path.write_bytes(backup_bytes)
    document = backup or _backup_document()
    manifest = {
        "manifest_version": 1,
        "created_at": document["created_at"],
        "schema_version": document["schema_version"],
        "privacy_warning": document["privacy_warning"],
        "artifacts": {
            "backup.json": {
                "sha256": checksum_file(backup_path),
                "bytes": backup_path.stat().st_size,
            }
        },
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return backup_path, manifest_path


@pytest.mark.parametrize(
    ("name", "backup_bytes", "expected_code"),
    [
        (
            "duplicate",
            json.dumps(_backup_document()).replace(
                '"backup_format_version": 1',
                '"backup_format_version": 1, "backup_format_version": 1',
                1,
            ).encode("utf-8"),
            "json_duplicate_key",
        ),
        ("encoding", b'{"backup_format_version":1,"private":"\xff"}', "document_encoding_invalid"),
        (
            "non-finite",
            json.dumps(_backup_document())
            .replace('"tables": {}', '"tables": {"workspaces": [NaN]}')
            .encode("utf-8"),
            "document_non_finite_number",
        ),
    ],
)
def test_backup_json_rejects_ambiguous_or_unsafe_input_before_target_mutation(
    tmp_path: Path,
    name: str,
    backup_bytes: bytes,
    expected_code: str,
) -> None:
    bundle = tmp_path / name
    _write_bundle(bundle, backup_bytes=backup_bytes)
    target = tmp_path / "existing.db"
    target.write_bytes(b"must-remain")

    with pytest.raises(DBBridgeError, match="could not be parsed") as captured:
        restore_backup(target, bundle, force=True)

    assert isinstance(captured.value.__cause__, StructuredDocumentError)
    assert captured.value.__cause__.code == expected_code
    assert target.read_bytes() == b"must-remain"
    assert not backup_module._temp_restore_path(target).exists()


def test_backup_json_rejects_depth_and_size_limits_before_target_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deep = _backup_document()
    nested: object = "value"
    for _index in range(70):
        nested = [nested]
    deep["tables"] = {"workspaces": [{"id": nested}]}
    deep_bundle = tmp_path / "deep"
    _write_bundle(deep_bundle, backup=deep)

    with pytest.raises(DBBridgeError) as deep_error:
        verify_backup(deep_bundle)
    assert isinstance(deep_error.value.__cause__, StructuredDocumentError)
    assert deep_error.value.__cause__.code == "document_depth_limit"

    small_policy = StructuredDocumentPolicy(
        max_file_bytes=1024,
        max_nodes=10_000,
        max_depth=64,
        max_collection_items=1_000,
        max_scalar_characters=4096,
        max_yaml_aliases=1,
    )
    monkeypatch.setattr(backup_module, "BACKUP_JSON_POLICY", small_policy)
    oversized = _backup_document()
    oversized["tables"] = {"workspaces": [{"id": "x" * 2048}]}
    oversized_bundle = tmp_path / "oversized"
    _write_bundle(oversized_bundle, backup=oversized)

    with pytest.raises(DBBridgeError) as size_error:
        verify_backup(oversized_bundle)
    assert isinstance(size_error.value.__cause__, StructuredDocumentError)
    assert size_error.value.__cause__.code == "document_size_limit"


def test_duplicate_manifest_is_rejected_before_backup_use(tmp_path: Path) -> None:
    bundle = tmp_path / "duplicate-manifest"
    _backup_path, manifest_path = _write_bundle(bundle)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        manifest_text.replace(
            '"manifest_version": 1',
            '"manifest_version": 1, "manifest_version": 1',
        ),
        encoding="utf-8",
    )

    with pytest.raises(DBBridgeError, match="could not be parsed") as captured:
        verify_backup(bundle)

    assert isinstance(captured.value.__cause__, StructuredDocumentError)
    assert captured.value.__cause__.code == "json_duplicate_key"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda backup: backup.__setitem__("unexpected", True), "Backup document is invalid"),
        (
            lambda backup: backup.__setitem__("backup_format_version", True),
            "Backup document is invalid",
        ),
        (
            lambda backup: backup["tables"].__setitem__("unregistered_table", []),
            "Backup document is invalid",
        ),
        (lambda backup: backup.__setitem__("excluded_tables", []), "Backup document is invalid"),
        (
            lambda backup: backup.__setitem__("latest_supported_schema_version", 0),
            "Backup document is invalid",
        ),
    ],
    ids=["extra-key", "boolean-version", "unknown-table", "excluded-table", "latest-version"],
)
def test_closed_backup_contract_rejects_invalid_documents(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    backup = _backup_document()
    mutation(backup)
    bundle = tmp_path / "invalid-backup"
    _write_bundle(bundle, backup=backup)

    with pytest.raises(DBBridgeError, match=message):
        verify_backup(bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: manifest.__setitem__("unexpected", True),
        lambda manifest: manifest.__setitem__("manifest_version", True),
        lambda manifest: manifest["artifacts"]["backup.json"].__setitem__("sha256", "bad"),
        lambda manifest: manifest["artifacts"]["backup.json"].__setitem__("bytes", False),
        lambda manifest: manifest.__setitem__("schema_version", 1),
    ],
    ids=["extra-key", "boolean-version", "checksum-shape", "boolean-bytes", "schema-mismatch"],
)
def test_closed_manifest_contract_rejects_invalid_documents(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    bundle = tmp_path / "invalid-manifest"
    _write_bundle(bundle, mutate_manifest=mutation)

    with pytest.raises(DBBridgeError, match="manifest"):
        verify_backup(bundle)


def test_backup_change_during_validation_is_rejected_before_force_target_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "changing"
    backup_path, _manifest_path = _write_bundle(bundle)
    target = tmp_path / "target.db"
    target.write_bytes(b"must-remain")
    original_reader = backup_module.read_json_document
    changed = False

    def mutate_after_read(path: Path, **kwargs: Any) -> object:
        nonlocal changed
        payload = original_reader(path, **kwargs)
        if Path(path) == backup_path and not changed:
            changed = True
            backup_path.write_bytes(backup_path.read_bytes() + b" ")
        return payload

    monkeypatch.setattr(backup_module, "read_json_document", mutate_after_read)

    with pytest.raises(DBBridgeError, match="changed during validation"):
        restore_backup(target, bundle, force=True)

    assert target.read_bytes() == b"must-remain"
    assert not backup_module._temp_restore_path(target).exists()


def test_nested_backup_reparse_is_rejected_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "reparse"
    backup_path, _manifest_path = _write_bundle(bundle)
    original = backup_module._path_is_reparse
    monkeypatch.setattr(
        backup_module,
        "_path_is_reparse",
        lambda path: Path(path) == backup_path or original(path),
    )

    with pytest.raises(DBBridgeError, match="could not be parsed"):
        verify_backup(bundle)


def test_generated_backup_and_manifest_match_published_schemas(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    run_migrations(db_path)
    artifacts = create_backup(db_path, tmp_path / "backup")
    backup_schema = json.loads(
        Path("docs/schemas/database_backup.schema.json").read_text(encoding="utf-8")
    )
    manifest_schema = json.loads(
        Path("docs/schemas/database_backup_manifest.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(backup_schema).validate(
        json.loads(artifacts.backup_path.read_text(encoding="utf-8"))
    )
    Draft202012Validator(manifest_schema).validate(
        json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    )
    assert verify_backup(artifacts.output_dir).ok is True


def test_backup_reader_has_no_direct_unbounded_json_read() -> None:
    tree = ast.parse(Path(backup_module.__file__).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert not any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "json"
        and call.func.attr in {"load", "loads"}
        for call in calls
    )
    assert not any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "read_text" for call in calls
    )
    assert backup_module.BACKUP_JSON_INGRESS_PROFILE == "database-backup-json-ingress-v1"
    assert backup_module.BACKUP_JSON_MAX_FILE_BYTES == 64 * 1024 * 1024
    assert backup_module.BACKUP_JSON_MAX_NODES == 1_000_000
    assert backup_module.BACKUP_JSON_MAX_COLLECTION_ITEMS == 250_000
    assert backup_module.BACKUP_JSON_MAX_SCALAR_CHARACTERS == 8 * 1024 * 1024
    assert backup_module.BACKUP_JSON_POLICY.max_file_bytes == backup_module.BACKUP_JSON_MAX_FILE_BYTES
    assert backup_module.BACKUP_JSON_POLICY.max_nodes == backup_module.BACKUP_JSON_MAX_NODES
    assert backup_module.BACKUP_JSON_POLICY.max_depth == 64
    assert (
        backup_module.BACKUP_JSON_POLICY.max_collection_items
        == backup_module.BACKUP_JSON_MAX_COLLECTION_ITEMS
    )
    assert (
        backup_module.BACKUP_JSON_POLICY.max_scalar_characters
        == backup_module.BACKUP_JSON_MAX_SCALAR_CHARACTERS
    )
