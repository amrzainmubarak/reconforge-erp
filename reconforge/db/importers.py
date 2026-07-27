"""Legacy JSON import helpers for the local DB migration bridge."""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from reconforge.close import load_close_checklist
from reconforge.db.connection import connect, resolve_db_path
from reconforge.db.exporter import (
    DBBridgeError,
    checksum_file,
    deterministic_bridge_id,
    resolve_input_file,
    resolve_local_path,
)
from reconforge.db.migrations import database_status
from reconforge.domain.models import utc_now_text
from reconforge.io.generated import GeneratedArtifactError
from reconforge.io.persisted import (
    PersistedJsonError,
    encode_sqlite_legacy_import_summary,
)
from reconforge.io.structured import (
    StructuredDocumentError,
    StructuredDocumentPolicy,
    read_json_document,
)
from reconforge.platform.common import PlatformError, commit_audited
from reconforge.review.state import load_review_state

LEGACY_DB_IMPORT_JSON_PROFILE = "database-legacy-import-json-ingress-v1"
LEGACY_DB_IMPORT_JSON_MAX_FILE_BYTES = 16 * 1024 * 1024
LEGACY_DB_IMPORT_JSON_MAX_NODES = 500_000
LEGACY_DB_IMPORT_JSON_MAX_DEPTH = 32
LEGACY_DB_IMPORT_JSON_MAX_COLLECTION_ITEMS = 50_000
LEGACY_DB_IMPORT_JSON_MAX_SCALAR_CHARACTERS = 1024 * 1024
LEGACY_DB_IMPORT_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=LEGACY_DB_IMPORT_JSON_MAX_FILE_BYTES,
    max_nodes=LEGACY_DB_IMPORT_JSON_MAX_NODES,
    max_depth=LEGACY_DB_IMPORT_JSON_MAX_DEPTH,
    max_collection_items=LEGACY_DB_IMPORT_JSON_MAX_COLLECTION_ITEMS,
    max_scalar_characters=LEGACY_DB_IMPORT_JSON_MAX_SCALAR_CHARACTERS,
    max_yaml_aliases=1,
)
_IMPORT_READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DBImportResult:
    """Result from one local legacy import operation."""

    source_type: str
    source_path: Path
    imported_count: int


def _clean_text(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _path_is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DBBridgeError("Input JSON could not be parsed.") from exc
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_attribute)


def _bounded_json_checksum(path: Path) -> tuple[str, int]:
    if _path_is_reparse(path):
        raise DBBridgeError("Input JSON could not be parsed.")
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise DBBridgeError("Input JSON could not be parsed.")
        if metadata.st_size > LEGACY_DB_IMPORT_JSON_POLICY.max_file_bytes:
            raise StructuredDocumentError("document_size_limit")
        digest = sha256()
        total = 0
        with path.open("rb") as handle:
            if os.fstat(handle.fileno()).st_size != metadata.st_size:
                raise StructuredDocumentError("document_size_changed")
            for chunk in iter(lambda: handle.read(_IMPORT_READ_CHUNK_BYTES), b""):
                total += len(chunk)
                if total > LEGACY_DB_IMPORT_JSON_POLICY.max_file_bytes:
                    raise StructuredDocumentError("document_size_limit")
                digest.update(chunk)
            if total != metadata.st_size or os.fstat(handle.fileno()).st_size != metadata.st_size:
                raise StructuredDocumentError("document_size_changed")
    except DBBridgeError:
        raise
    except (OSError, StructuredDocumentError) as exc:
        raise DBBridgeError("Input JSON could not be parsed.") from exc
    return digest.hexdigest(), total


def _read_json(path: Path) -> tuple[object, str, int]:
    before_checksum, before_size = _bounded_json_checksum(path)
    try:
        payload = read_json_document(path, policy=LEGACY_DB_IMPORT_JSON_POLICY)
    except (OSError, StructuredDocumentError) as exc:
        raise DBBridgeError("Input JSON could not be parsed.") from exc
    after_checksum, after_size = _bounded_json_checksum(path)
    if before_checksum != after_checksum or before_size != after_size:
        raise DBBridgeError("Input JSON could not be parsed.")
    return payload, after_checksum, after_size


def _ensure_current_database(db_path: Path | str) -> Path:
    resolved = resolve_db_path(db_path)
    status = database_status(resolved)
    if status.pending_versions:
        raise DBBridgeError("ReconForge database has pending migrations. Run 'reconforge db migrate' first.")
    return resolved


def _records_from_payload(payload: object, *, preferred_keys: tuple[str, ...], label: str) -> list[dict[str, Any]]:
    raw_records: object = payload
    if isinstance(payload, dict):
        present_keys = [key for key in preferred_keys if key in payload]
        if len(present_keys) > 1:
            raise DBBridgeError(f"{label} JSON contains ambiguous record collections.")
        if present_keys:
            raw_records = payload[present_keys[0]]
        elif not payload or all(isinstance(value, dict) for value in payload.values()):
            if payload:
                mapped_records = []
                for key, value in payload.items():
                    record = dict(value)
                    record.setdefault("id", key)
                    mapped_records.append(record)
                return mapped_records
            return []
        else:
            raise DBBridgeError(f"{label} JSON must contain a list or object map of records.")
    if not isinstance(raw_records, list):
        raise DBBridgeError(f"{label} JSON must contain a list of records.")
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise DBBridgeError(f"Each {label} record must be an object.")
        records.append(dict(raw))
    return records


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean_text(record.get(key, ""))
        if value:
            return value
    return ""


def _safe_summary(record: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in keys:
        value = _clean_text(record.get(key, ""))
        if value:
            summary[key] = value[:500]
    return summary


def _upsert_workflow_object(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
    status: str,
    timestamp: str,
) -> None:
    existing = connection.execute(
        "SELECT id, created_at FROM workflow_objects WHERE object_type = ? AND object_id = ?",
        (object_type, object_id),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO workflow_objects (id, object_type, object_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deterministic_bridge_id("WF", object_type, object_id),
                object_type,
                object_id,
                status,
                timestamp,
                timestamp,
            ),
        )
        return
    connection.execute(
        """
        UPDATE workflow_objects
        SET status = ?, updated_at = ?
        WHERE object_type = ? AND object_id = ?
        """,
        (status, timestamp, object_type, object_id),
    )


def _upsert_legacy_record(
    connection: sqlite3.Connection,
    *,
    source_type: str,
    object_type: str,
    object_id: str,
    status: str,
    source_path: Path,
    source_checksum: str,
    summary: dict[str, Any],
    timestamp: str,
) -> None:
    try:
        payload = encode_sqlite_legacy_import_summary(summary).text
    except PersistedJsonError as exc:
        raise DBBridgeError("Legacy import summary is invalid.") from exc
    existing = connection.execute(
        """
        SELECT id FROM legacy_import_records
        WHERE source_type = ? AND object_type = ? AND object_id = ?
        """,
        (source_type, object_type, object_id),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO legacy_import_records (
                id, source_type, object_type, object_id, status, source_path,
                source_checksum_sha256, summary_json, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deterministic_bridge_id("LEG", source_type, object_type, object_id),
                source_type,
                object_type,
                object_id,
                status,
                source_path.name,
                source_checksum,
                payload,
                timestamp,
            ),
        )
        return
    connection.execute(
        """
        UPDATE legacy_import_records
        SET status = ?, source_path = ?, source_checksum_sha256 = ?, summary_json = ?, imported_at = ?
        WHERE source_type = ? AND object_type = ? AND object_id = ?
        """,
        (
            status,
            source_path.name,
            source_checksum,
            payload,
            timestamp,
            source_type,
            object_type,
            object_id,
        ),
    )


def _import_records(
    db_path: Path | str,
    source_path: Path,
    *,
    source_type: str,
    object_type: str,
    records: list[dict[str, Any]],
    id_keys: tuple[str, ...],
    status_keys: tuple[str, ...],
    default_status: str,
    summary_keys: tuple[str, ...],
    audit_action: str,
    actor_label: str,
    source_checksum: str | None = None,
    source_size_bytes: int | None = None,
    ingress_profile: str | None = None,
) -> DBImportResult:
    resolved_db_path = _ensure_current_database(db_path)
    checksum = source_checksum or checksum_file(source_path)
    timestamp = utc_now_text()
    connection = connect(resolved_db_path, require_exists=True)
    try:
        imported = 0
        for record in records:
            object_id = _first_text(record, id_keys)
            if not object_id:
                raise DBBridgeError(f"{source_type} record is missing a required identifier.")
            status = _first_text(record, status_keys) or default_status
            summary = _safe_summary(record, summary_keys)
            summary["source_type"] = source_type
            if ingress_profile is not None:
                summary["ingress_profile"] = ingress_profile
            if source_size_bytes is not None:
                summary["source_size_bytes"] = source_size_bytes
            _upsert_workflow_object(
                connection,
                object_type=object_type,
                object_id=object_id,
                status=status,
                timestamp=timestamp,
            )
            _upsert_legacy_record(
                connection,
                source_type=source_type,
                object_type=object_type,
                object_id=object_id,
                status=status,
                source_path=source_path,
                source_checksum=checksum,
                summary=summary,
                timestamp=timestamp,
            )
            imported += 1
        commit_audited(
            connection,
            actor_label=actor_label,
            object_type="db_bridge",
            object_id=source_type,
            action=audit_action,
            metadata={
                "source_type": source_type,
                "source_file": source_path.name,
                "source_checksum_sha256": checksum,
                "imported_count": imported,
                **({"ingress_profile": ingress_profile} if ingress_profile is not None else {}),
                **({"source_size_bytes": source_size_bytes} if source_size_bytes is not None else {}),
            },
            emit_outbox=True,
            outbox_event_type="legacy_import_completed",
            outbox_aggregate_type="legacy_import",
            outbox_aggregate_id=source_type,
            outbox_payload={
                "source_type": source_type,
                "source_file": source_path.name,
                "source_checksum_sha256": checksum,
                "imported_count": imported,
                "audit_action": audit_action,
                **({"ingress_profile": ingress_profile} if ingress_profile is not None else {}),
                **({"source_size_bytes": source_size_bytes} if source_size_bytes is not None else {}),
            },
        )
    except DBBridgeError:
        connection.rollback()
        raise
    except (sqlite3.DatabaseError, OSError, TypeError, ValueError, PlatformError) as exc:
        connection.rollback()
        raise DBBridgeError(f"Unable to import {source_type} records.") from exc
    finally:
        connection.close()
    return DBImportResult(source_type=source_type, source_path=source_path, imported_count=imported)


def import_review_state(
    db_path: Path | str,
    input_path: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBImportResult:
    """Import legacy review_state.json into DB workflow references."""

    source_path = resolve_input_file(input_path)
    try:
        state = load_review_state(source_path)
    except GeneratedArtifactError as exc:
        raise DBBridgeError("Unable to import review state records.") from exc
    records = [dict(entry) for _, entry in sorted(state.items())]
    return _import_records(
        db_path,
        source_path,
        source_type="review_state",
        object_type="legacy_review_exception",
        records=records,
        id_keys=("exception_id", "id"),
        status_keys=("status",),
        default_status="New",
        summary_keys=(
            "exception_id",
            "status",
            "reviewer",
            "updated_at",
            "decision_reason",
            "accepted_risk_reason",
            "escalation_owner",
            "certification_status",
        ),
        audit_action="legacy_review_state_imported",
        actor_label=actor_label,
    )


def import_close_checklist(
    db_path: Path | str,
    input_path: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBImportResult:
    """Import legacy close_checklist.json task state into DB workflow references."""

    resolved = resolve_local_path(input_path)
    source_path = resolved / "close_checklist.json" if resolved.is_dir() else resolved
    checklist = load_close_checklist(source_path)
    records = [dict(task) for task in checklist.get("tasks", [])]
    return _import_records(
        db_path,
        source_path,
        source_type="close_checklist",
        object_type="close_task",
        records=records,
        id_keys=("task_id", "id"),
        status_keys=("status",),
        default_status="Not Started",
        summary_keys=("task_id", "task_name", "category", "owner", "due_date", "status", "updated_at"),
        audit_action="legacy_close_checklist_imported",
        actor_label=actor_label,
    )


def import_account_reconciliations(
    db_path: Path | str,
    input_path: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBImportResult:
    """Import legacy account_reconciliations.json summaries into DB references."""

    source_path = resolve_input_file(input_path, expected_name="account_reconciliations.json")
    payload, source_checksum, source_size = _read_json(source_path)
    records = _records_from_payload(
        payload,
        preferred_keys=("account_reconciliations", "reconciliations", "records", "items"),
        label="account reconciliation",
    )
    return _import_records(
        db_path,
        source_path,
        source_type="account_reconciliations",
        object_type="legacy_account_reconciliation",
        records=records,
        id_keys=("reconciliation_id", "account_reconciliation_id", "account_id", "account_code", "id"),
        status_keys=("status", "review_status", "reconciliation_status"),
        default_status="Draft",
        summary_keys=(
            "reconciliation_id",
            "account_id",
            "account_code",
            "account_name",
            "period",
            "entity",
            "owner",
            "preparer",
            "reviewer",
            "status",
            "materiality",
        ),
        audit_action="legacy_account_reconciliations_imported",
        actor_label=actor_label,
        source_checksum=source_checksum,
        source_size_bytes=source_size,
        ingress_profile=LEGACY_DB_IMPORT_JSON_PROFILE,
    )


def import_control_tests(
    db_path: Path | str,
    input_path: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBImportResult:
    """Import legacy control_tests.json summaries into DB references."""

    source_path = resolve_input_file(input_path, expected_name="control_tests.json")
    payload, source_checksum, source_size = _read_json(source_path)
    records = _records_from_payload(
        payload,
        preferred_keys=("control_tests", "tests", "records", "items"),
        label="control test",
    )
    return _import_records(
        db_path,
        source_path,
        source_type="control_tests",
        object_type="control_test",
        records=records,
        id_keys=("test_id", "control_test_id", "control_id", "control_code", "id"),
        status_keys=("status", "test_status", "result_status"),
        default_status="Draft",
        summary_keys=(
            "test_id",
            "control_id",
            "control_code",
            "control_name",
            "frequency",
            "owner",
            "tester",
            "status",
            "result",
            "period",
        ),
        audit_action="legacy_control_tests_imported",
        actor_label=actor_label,
        source_checksum=source_checksum,
        source_size_bytes=source_size,
        ingress_profile=LEGACY_DB_IMPORT_JSON_PROFILE,
    )
