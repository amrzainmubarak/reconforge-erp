"""Safe local DB export helpers for the migration bridge."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from shutil import rmtree
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any

from reconforge.audit import append_audit_event
from reconforge.db.connection import connect, resolve_db_path
from reconforge.db.migrations import database_status
from reconforge.io.persisted import (
    PersistedJsonError,
    PersistedJsonObjectDocument,
    decode_audit_metadata,
    decode_sqlite_legacy_import_summary,
    decode_sqlite_matching_lineage,
    decode_sqlite_matching_rule,
)
from reconforge.io.structured import StructuredDocumentError, read_json_document

EXPORT_FORMAT_VERSION = 1
EXPORT_MANIFEST_VERSION = 1
EXPORT_ARTIFACT_NAMES = frozenset(
    {
        "audit_events.json",
        "domain.json",
        "evidence.json",
        "finance_workflows.json",
        "identity.json",
        "inventory.json",
        "legacy_imports.json",
        "metadata.json",
        "workflow.json",
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_MARKER_PHASES = {"prepared", "previous-moved", "published"}
_MARKER_BOUNDARY = "Local crash-recovery integrity marker; SHA-256 detects change but is not authentication."

SELECT_QUERIES = {
    "workspaces": "SELECT * FROM workspaces ORDER BY created_at, id",
    "organizations": "SELECT * FROM organizations ORDER BY created_at, id",
    "currencies": "SELECT * FROM currencies ORDER BY code",
    "legal_entities": "SELECT * FROM legal_entities ORDER BY entity_code, id",
    "branches": "SELECT * FROM branches ORDER BY organization_id, branch_code, id",
    "periods": "SELECT * FROM periods ORDER BY start_date, id",
    "units_of_measure": "SELECT * FROM units_of_measure ORDER BY workspace_id, uom_code",
    "inventory_items": "SELECT * FROM inventory_items ORDER BY workspace_id, item_code",
    "warehouses": "SELECT * FROM warehouses ORDER BY workspace_id, organization_id, warehouse_code",
    "inventory_locations": "SELECT * FROM inventory_locations ORDER BY warehouse_id, location_code",
    "inventory_lots": "SELECT * FROM inventory_lots ORDER BY item_id, organization_id, lot_serial_code",
    "inventory_movements": "SELECT * FROM inventory_movements ORDER BY workspace_id, movement_date, movement_number",
    "inventory_movement_lines": "SELECT * FROM inventory_movement_lines ORDER BY movement_id, line_number",
    "inventory_count_sessions": "SELECT * FROM inventory_count_sessions ORDER BY workspace_id, count_date, count_number",
    "inventory_count_lines": "SELECT * FROM inventory_count_lines ORDER BY session_id, line_number",
    "inventory_reorder_rules": "SELECT * FROM inventory_reorder_rules ORDER BY workspace_id, organization_id, legal_entity_id, item_id, location_id",
    "inventory_valuation_policies": "SELECT * FROM inventory_valuation_policies ORDER BY workspace_id, organization_id, legal_entity_id, policy_code",
    "inventory_valuation_documents": "SELECT * FROM inventory_valuation_documents ORDER BY workspace_id, valuation_date, valuation_number",
    "inventory_valuation_input_costs": "SELECT * FROM inventory_valuation_input_costs ORDER BY valuation_document_id, movement_line_id",
    "inventory_valuation_lines": "SELECT * FROM inventory_valuation_lines ORDER BY valuation_document_id, line_number",
    "inventory_cost_layers": "SELECT * FROM inventory_cost_layers ORDER BY created_at, id",
    "inventory_layer_consumptions": "SELECT * FROM inventory_layer_consumptions ORDER BY valuation_line_id, cost_layer_id",
    "inventory_valuation_reversals": "SELECT * FROM inventory_valuation_reversals ORDER BY workspace_id, reversal_date, reversal_number",
    "inventory_valuation_reversal_effects": "SELECT * FROM inventory_valuation_reversal_effects ORDER BY reversal_id, original_valuation_line_id, id",
    "charts_of_accounts": "SELECT * FROM charts_of_accounts ORDER BY workspace_id, chart_code",
    "accounting_dimensions": "SELECT * FROM accounting_dimensions ORDER BY workspace_id, dimension_code",
    "accounting_dimension_values": "SELECT * FROM accounting_dimension_values ORDER BY dimension_id, value_code",
    "users_public": """
        SELECT id, username, display_name, email, disabled, created_at, password_changed_at,
               failed_login_count, locked_until
        FROM users
        ORDER BY username
    """,
    "roles": "SELECT * FROM roles ORDER BY name",
    "permissions": "SELECT * FROM permissions ORDER BY name",
    "user_roles": "SELECT * FROM user_roles ORDER BY user_id, role_id",
    "role_permissions": "SELECT * FROM role_permissions ORDER BY role_id, permission_name",
    "accounts": "SELECT * FROM accounts ORDER BY account_code, id",
    "finance_journals": "SELECT * FROM finance_journals ORDER BY workspace_id, organization_id, journal_code",
    "ledger_entries": "SELECT * FROM ledger_entries ORDER BY workspace_id, posting_date, entry_number",
    "ledger_lines": "SELECT * FROM ledger_lines ORDER BY entry_id, line_number",
    "ledger_line_dimensions": "SELECT * FROM ledger_line_dimensions ORDER BY line_id, dimension_value_id",
    "reconciliations": "SELECT * FROM reconciliations ORDER BY created_at, id",
    "tasks": "SELECT * FROM tasks ORDER BY created_at, id",
    "controls": "SELECT * FROM controls ORDER BY control_code, id",
    "evidence_objects": "SELECT * FROM evidence_objects ORDER BY created_at, id",
    "workflow_objects": "SELECT * FROM workflow_objects ORDER BY object_type, object_id",
    "workflow_transitions": "SELECT * FROM workflow_transitions ORDER BY object_type, from_status, to_status, id",
    "workflow_transition_events": "SELECT * FROM workflow_transition_events ORDER BY created_at, id",
    "audit_events": "SELECT * FROM audit_events ORDER BY sequence",
    "legacy_import_records": "SELECT * FROM legacy_import_records ORDER BY source_type, object_type, object_id",
    "account_reconciliation_templates": "SELECT * FROM account_reconciliation_templates ORDER BY workspace_id, account_code",
    "trial_balance_rows": "SELECT * FROM trial_balance_rows ORDER BY workspace_id, period_name, entity_code, account_code, source_row_number",
    "account_reconciliation_records": "SELECT * FROM account_reconciliation_records ORDER BY workspace_id, period_name, entity_code, account_code",
    "account_reconciliation_items": "SELECT * FROM account_reconciliation_items ORDER BY reconciliation_id, created_at, id",
    "account_reconciliation_support": "SELECT * FROM account_reconciliation_support ORDER BY reconciliation_id, evidence_id",
    "close_periods": "SELECT * FROM close_periods ORDER BY workspace_id, period_name",
    "close_tasks_db": "SELECT * FROM close_tasks_db ORDER BY close_period_id, task_code",
    "close_task_dependencies": "SELECT * FROM close_task_dependencies ORDER BY close_period_id, task_id, depends_on_task_id",
    "approval_requests": "SELECT * FROM approval_requests ORDER BY created_at, id",
    "certification_records": "SELECT * FROM certification_records ORDER BY object_type, object_id",
    "evidence_registry": "SELECT * FROM evidence_registry ORDER BY workspace_id, evidence_code",
    "evidence_requirements": "SELECT * FROM evidence_requirements ORDER BY workspace_id, object_type, object_id, requirement_code",
    "evidence_links": "SELECT * FROM evidence_links ORDER BY object_type, object_id, evidence_id",
    "journal_entries": "SELECT * FROM journal_entries ORDER BY workspace_id, period_name, journal_id",
    "journal_exceptions": "SELECT * FROM journal_exceptions ORDER BY journal_entry_id, policy_code",
    "intercompany_transactions": "SELECT * FROM intercompany_transactions ORDER BY workspace_id, period_name, transaction_id",
    "intercompany_cases": "SELECT * FROM intercompany_cases ORDER BY workspace_id, period_name, entity_code, counterparty_code, reference",
    "control_library": "SELECT * FROM control_library ORDER BY workspace_id, control_code",
    "control_test_plans": "SELECT * FROM control_test_plans ORDER BY workspace_id, period_name, control_id",
    "control_test_samples": "SELECT * FROM control_test_samples ORDER BY test_plan_id, sample_reference",
    "control_test_results": "SELECT * FROM control_test_results ORDER BY test_plan_id, created_at, id",
    "remediation_plans": "SELECT * FROM remediation_plans ORDER BY source_type, source_id",
    "match_jobs": "SELECT * FROM match_jobs ORDER BY created_at, id",
    "match_rules": "SELECT * FROM match_rules ORDER BY job_id, rule_name",
    "match_results": "SELECT * FROM match_results ORDER BY job_id, left_id, right_id, match_type",
    "exceptions_queue": "SELECT * FROM exceptions_queue ORDER BY status, risk_rating, created_at, id",
    "metric_definitions": "SELECT * FROM metric_definitions ORDER BY metric_key",
    "metric_snapshots": "SELECT * FROM metric_snapshots ORDER BY workspace_id, period_name, metric_key",
    "ops_job_history": "SELECT * FROM ops_job_history ORDER BY started_at, id",
    "ops_error_records": "SELECT * FROM ops_error_records ORDER BY created_at, id",
}

# Exact inventory of structured values reachable from the public DB export.
# ``output_name=None`` validates while preserving the historical raw field.
EXPORT_JSON_FIELDS: Mapping[
    tuple[str, str],
    tuple[Callable[[object], PersistedJsonObjectDocument], str | None],
] = MappingProxyType(
    {
        ("audit_events", "metadata_json"): (decode_audit_metadata, "metadata"),
        ("legacy_import_records", "summary_json"): (
            decode_sqlite_legacy_import_summary,
            "summary",
        ),
        ("match_jobs", "rule_json"): (decode_sqlite_matching_rule, "rule"),
        ("match_rules", "rule_json"): (decode_sqlite_matching_rule, "rule"),
        ("match_results", "lineage_json"): (decode_sqlite_matching_lineage, None),
    }
)


class DBBridgeError(ValueError):
    """Raised for safe, user-facing DB bridge errors."""


@dataclass(frozen=True)
class DBExportResult:
    """Files written by the local DB export bridge."""

    output_dir: Path
    paths: list[Path]
    schema_version: int


@dataclass(frozen=True)
class DBExportPublicationRecovery:
    """Result of an explicit interrupted export publication recovery."""

    transaction_id: str
    action: str


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def resolve_local_path(path: Path | str) -> Path:
    """Resolve a local path while rejecting traversal-oriented inputs."""

    raw = str(path)
    if not raw.strip() or _has_control_character(raw):
        raise DBBridgeError("Unsafe local path. Use a normal local path without control characters.")
    candidate = Path(path).expanduser()
    if any(part == ".." for part in candidate.parts):
        raise DBBridgeError("Unsafe local path. Parent traversal segments are not allowed.")
    if candidate.exists() and candidate.is_symlink():
        raise DBBridgeError("Unsafe local path. Symlinks are not allowed for DB bridge operations.")
    if candidate.parent.exists() and not candidate.parent.is_dir():
        raise DBBridgeError("Unsafe local path. Parent path is not a directory.")
    return candidate.resolve(strict=False)


def resolve_output_dir(path: Path | str) -> Path:
    """Resolve and create a local output directory."""

    output_dir = resolve_local_path(path)
    if output_dir.exists() and not output_dir.is_dir():
        raise DBBridgeError("Output path must be a local directory.")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def resolve_input_file(path: Path | str, *, expected_name: str | None = None) -> Path:
    """Resolve an existing local input file."""

    input_path = resolve_local_path(path)
    if expected_name is not None and input_path.is_dir():
        input_path = input_path / expected_name
    if not input_path.exists() or not input_path.is_file():
        raise DBBridgeError("Input file not found.")
    return input_path


def checksum_file(path: Path) -> str:
    """Return a SHA-256 checksum for a local file."""

    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_bridge_id(prefix: str, *parts: object) -> str:
    """Return a deterministic local ID for bridge-created reference records."""

    payload = "|".join(str(part).strip() for part in parts)
    return f"{prefix}-{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def write_json_file(path: Path, payload: dict[str, Any]) -> Path:
    """Write deterministic JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _path_is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DBBridgeError("Database export publication path is unreadable.") from exc
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _publication_siblings(output_dir: Path, kind: str) -> list[Path]:
    prefix = f".{output_dir.name}.{kind}-"
    return sorted(
        (path for path in output_dir.parent.iterdir() if path.name.startswith(prefix)),
        key=lambda path: path.name,
    )


def _expected_artifacts(root: Path) -> dict[str, dict[str, object]]:
    manifest_path = root / "export_manifest.json"
    try:
        document = read_json_document(manifest_path)
    except (OSError, StructuredDocumentError) as exc:
        raise DBBridgeError("Database export manifest is invalid.") from exc
    if not isinstance(document, dict) or set(document) != {
        "artifact_type",
        "export_format_version",
        "manifest_version",
        "schema_version",
        "artifacts",
    }:
        raise DBBridgeError("Database export manifest is invalid.")
    artifacts = document.get("artifacts")
    if (
        document.get("artifact_type") != "reconforge_database_export"
        or document.get("export_format_version") != EXPORT_FORMAT_VERSION
        or document.get("manifest_version") != EXPORT_MANIFEST_VERSION
        or not isinstance(document.get("schema_version"), int)
        or not isinstance(artifacts, dict)
    ):
        raise DBBridgeError("Database export manifest is invalid.")
    if set(artifacts) != EXPORT_ARTIFACT_NAMES:
        raise DBBridgeError("Database export manifest is invalid.")
    validated: dict[str, dict[str, object]] = {}
    for name, record in artifacts.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".json")
            or not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or not isinstance(record.get("bytes"), int)
            or record["bytes"] < 0
            or not isinstance(record.get("sha256"), str)
            or _SHA256_PATTERN.fullmatch(record["sha256"]) is None
        ):
            raise DBBridgeError("Database export manifest is invalid.")
        validated[name] = record
    actual_names = {path.name for path in root.iterdir()}
    if actual_names != {*validated, "export_manifest.json"}:
        raise DBBridgeError("Database export artifact set does not match its manifest.")
    for name, record in validated.items():
        path = root / name
        if _path_is_reparse(path) or not path.is_file():
            raise DBBridgeError("Database export artifact is invalid.")
        if path.stat().st_size != record["bytes"] or not hmac.compare_digest(
            checksum_file(path), str(record["sha256"])
        ):
            raise DBBridgeError("Database export artifact integrity check failed.")
    return validated


def _tree_digest(root: Path) -> str:
    artifacts = _expected_artifacts(root)
    manifest = read_json_document(root / "export_manifest.json")
    return _canonical_digest({"manifest": manifest, "artifacts": artifacts})


def _bounded_directory_digest(root: Path) -> str:
    """Digest a prior export without requiring the newer additive manifest."""

    records: list[dict[str, object]] = []
    total_bytes = 0
    paths = sorted(root.iterdir(), key=lambda path: path.name)
    if len(paths) > 32:
        raise DBBridgeError("Existing database export exceeds the recovery file limit.")
    for path in paths:
        if _path_is_reparse(path) or not path.is_file():
            raise DBBridgeError("Existing database export contains an unsupported entry.")
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > 1024 * 1024 * 1024:
            raise DBBridgeError("Existing database export exceeds the recovery byte limit.")
        records.append({"name": path.name, "bytes": size, "sha256": checksum_file(path)})
    return _canonical_digest(records)


def _write_marker(path: Path, payload: dict[str, object]) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _marker_payload(
    output: Path, staging: Path, rollback: Path, transaction_id: str, previous: str, staged: str, phase: str
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": "reconforge_db_export_publication",
        "transaction_id": transaction_id,
        "output_name": output.name,
        "staging_name": staging.name,
        "rollback_name": rollback.name,
        "phase": phase,
        "previous_tree_digest": previous,
        "staged_tree_digest": staged,
        "integrity_boundary": _MARKER_BOUNDARY,
    }
    payload["marker_digest"] = _canonical_digest(payload)
    return payload


def _read_marker(output: Path, path: Path) -> dict[str, object]:
    try:
        document = read_json_document(path)
    except (OSError, StructuredDocumentError) as exc:
        raise DBBridgeError("Database export publication marker is invalid.") from exc
    required = {
        "schema_version",
        "artifact_type",
        "transaction_id",
        "output_name",
        "staging_name",
        "rollback_name",
        "phase",
        "previous_tree_digest",
        "staged_tree_digest",
        "integrity_boundary",
        "marker_digest",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise DBBridgeError("Database export publication marker is invalid.")
    transaction_id = document.get("transaction_id")
    if (
        document.get("schema_version") != 1
        or document.get("artifact_type") != "reconforge_db_export_publication"
        or document.get("integrity_boundary") != _MARKER_BOUNDARY
        or not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or document.get("phase") not in _MARKER_PHASES
        or document.get("output_name") != output.name
        or document.get("staging_name") != f".{output.name}.staging-{transaction_id}"
        or document.get("rollback_name") != f".{output.name}.rollback-{transaction_id}"
        or path.name != f".{output.name}.db-export-transaction-{transaction_id}.json"
    ):
        raise DBBridgeError("Database export publication marker is invalid.")
    for key in ("previous_tree_digest", "staged_tree_digest", "marker_digest"):
        if not isinstance(document.get(key), str) or _SHA256_PATTERN.fullmatch(str(document[key])) is None:
            raise DBBridgeError("Database export publication marker is invalid.")
    unsigned = {key: value for key, value in document.items() if key != "marker_digest"}
    if not hmac.compare_digest(str(document["marker_digest"]), _canonical_digest(unsigned)):
        raise DBBridgeError("Database export publication marker is invalid.")
    return document


def _ensure_siblings(output: Path, expected: set[Path]) -> None:
    found = {
        *_publication_siblings(output, "staging"),
        *_publication_siblings(output, "rollback"),
        *_publication_siblings(output, "db-export-transaction"),
    }
    if found != {path for path in expected if path.exists()}:
        raise DBBridgeError("Database export publication recovery state is ambiguous.")


def _publish_staged_export(staging: Path, output: Path) -> None:
    staged_digest = _tree_digest(staging)
    if not output.exists():
        _ensure_siblings(output, {staging})
        staging.replace(output)
        return
    _ensure_siblings(output, {staging})
    transaction_id = staging.name.removeprefix(f".{output.name}.staging-")
    if re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None:
        raise DBBridgeError("Database export staging directory is invalid.")
    rollback = output.parent / f".{output.name}.rollback-{transaction_id}"
    marker_path = output.parent / f".{output.name}.db-export-transaction-{transaction_id}.json"
    previous_digest = _bounded_directory_digest(output)
    marker = _marker_payload(output, staging, rollback, transaction_id, previous_digest, staged_digest, "prepared")
    _write_marker(marker_path, marker)
    try:
        output.replace(rollback)
        marker = _marker_payload(
            output, staging, rollback, transaction_id, previous_digest, staged_digest, "previous-moved"
        )
        _write_marker(marker_path, marker)
        staging.replace(output)
        marker = _marker_payload(output, staging, rollback, transaction_id, previous_digest, staged_digest, "published")
        _write_marker(marker_path, marker)
        rmtree(rollback)
        marker_path.unlink()
    except Exception:
        if output.exists() and not staging.exists() and rollback.exists():
            output.replace(staging)
        if rollback.exists() and not output.exists():
            rollback.replace(output)
        if staging.exists():
            rmtree(staging)
        marker_path.unlink(missing_ok=True)
        raise


def recover_database_export_publication(output_dir: Path | str) -> DBExportPublicationRecovery:
    """Recover exactly one integrity-verified interrupted export publication."""

    output = resolve_local_path(output_dir)
    if not output.name or not output.parent.is_dir() or _path_is_reparse(output):
        raise DBBridgeError("Database export publication recovery output is invalid.")
    markers = _publication_siblings(output, "db-export-transaction")
    if len(markers) != 1 or _path_is_reparse(markers[0]):
        raise DBBridgeError("Database export publication recovery requires exactly one valid marker.")
    marker_path = markers[0]
    marker = _read_marker(output, marker_path)
    transaction_id = str(marker["transaction_id"])
    staging = output.parent / str(marker["staging_name"])
    rollback = output.parent / str(marker["rollback_name"])
    _ensure_siblings(output, {staging, rollback, marker_path})
    for path in (staging, rollback):
        if _path_is_reparse(path) or (path.exists() and not path.is_dir()):
            raise DBBridgeError("Database export publication recovery state is invalid.")
    state = (output.exists(), staging.exists(), rollback.exists())
    phase = marker["phase"]
    previous, staged = str(marker["previous_tree_digest"]), str(marker["staged_tree_digest"])
    if (
        state == (True, True, False)
        and phase == "prepared"
        and _bounded_directory_digest(output) == previous
        and _tree_digest(staging) == staged
    ):
        rmtree(staging)
        marker_path.unlink()
        action = "aborted-before-swap"
    elif (
        state == (False, True, True)
        and phase in {"prepared", "previous-moved"}
        and _bounded_directory_digest(rollback) == previous
        and _tree_digest(staging) == staged
    ):
        rollback.replace(output)
        rmtree(staging)
        marker_path.unlink()
        action = "restored-previous"
    elif (
        state == (True, False, True)
        and phase in {"previous-moved", "published"}
        and _bounded_directory_digest(rollback) == previous
        and _tree_digest(output) == staged
    ):
        rmtree(rollback)
        marker_path.unlink()
        action = "finalized-published"
    elif state == (True, False, False) and phase == "published" and _tree_digest(output) == staged:
        marker_path.unlink()
        action = "confirmed-published"
    else:
        raise DBBridgeError("Database export publication recovery state is ambiguous or fails integrity verification.")
    return DBExportPublicationRecovery(transaction_id=transaction_id, action=action)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(connection, table):
        return []
    query = SELECT_QUERIES.get(table)
    if query is None:
        raise DBBridgeError("Unsupported export table.")
    rows = connection.execute(query).fetchall()
    return [dict(row) for row in rows]


def _json_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    records = _rows(connection, table)
    field_contracts = {
        column: contract for (field_table, column), contract in EXPORT_JSON_FIELDS.items() if field_table == table
    }
    for record in records:
        for column, (decoder, output_name) in field_contracts.items():
            value = record.get(column)
            if not isinstance(value, str):
                raise DBBridgeError(f"Stored {table}.{column} is invalid.")
            try:
                document = decoder(value)
            except PersistedJsonError as exc:
                raise DBBridgeError(f"Stored {table}.{column} is invalid.") from exc
            if output_name is not None:
                record[output_name] = document.payload
                del record[column]
    return records


def _schema_version(db_path: Path | str) -> int:
    status = database_status(db_path)
    if status.pending_versions:
        raise DBBridgeError("ReconForge database has pending migrations. Run 'reconforge db migrate' first.")
    return status.current_version


def _domain_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "workspaces": _rows(connection, "workspaces"),
        "organizations": _rows(connection, "organizations"),
        "currencies": _rows(connection, "currencies"),
        "legal_entities": _rows(connection, "legal_entities"),
        "branches": _rows(connection, "branches"),
        "periods": _rows(connection, "periods"),
        "charts_of_accounts": _rows(connection, "charts_of_accounts"),
        "accounting_dimensions": _rows(connection, "accounting_dimensions"),
        "accounting_dimension_values": _rows(connection, "accounting_dimension_values"),
        "accounts": _rows(connection, "accounts"),
        "reconciliations": _rows(connection, "reconciliations"),
        "tasks": _rows(connection, "tasks"),
        "controls": _rows(connection, "controls"),
    }


def _identity_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "users": [dict(row) for row in connection.execute(SELECT_QUERIES["users_public"]).fetchall()],
        "roles": _rows(connection, "roles"),
        "permissions": _rows(connection, "permissions"),
        "user_roles": _rows(connection, "user_roles"),
        "role_permissions": _rows(connection, "role_permissions"),
        "credential_material_note": "Local password credential columns and local session rows are intentionally excluded.",
    }


def _workflow_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "workflow_objects": _rows(connection, "workflow_objects"),
        "workflow_transitions": _rows(connection, "workflow_transitions"),
        "workflow_transition_events": _rows(connection, "workflow_transition_events"),
    }


def _audit_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "audit_events": _json_rows(connection, "audit_events"),
    }


def _legacy_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "legacy_import_records": _json_rows(connection, "legacy_import_records"),
    }


def _finance_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "finance_journals": _rows(connection, "finance_journals"),
        "ledger_entries": _rows(connection, "ledger_entries"),
        "ledger_lines": _rows(connection, "ledger_lines"),
        "ledger_line_dimensions": _rows(connection, "ledger_line_dimensions"),
        "account_reconciliation_templates": _rows(connection, "account_reconciliation_templates"),
        "trial_balance_rows": _rows(connection, "trial_balance_rows"),
        "account_reconciliation_records": _rows(connection, "account_reconciliation_records"),
        "account_reconciliation_items": _rows(connection, "account_reconciliation_items"),
        "account_reconciliation_support": _rows(connection, "account_reconciliation_support"),
        "close_periods": _rows(connection, "close_periods"),
        "close_tasks": _rows(connection, "close_tasks_db"),
        "close_task_dependencies": _rows(connection, "close_task_dependencies"),
        "approval_requests": _rows(connection, "approval_requests"),
        "certification_records": _rows(connection, "certification_records"),
        "journal_entries": _rows(connection, "journal_entries"),
        "journal_exceptions": _rows(connection, "journal_exceptions"),
        "intercompany_transactions": _rows(connection, "intercompany_transactions"),
        "intercompany_cases": _rows(connection, "intercompany_cases"),
        "control_library": _rows(connection, "control_library"),
        "control_test_plans": _rows(connection, "control_test_plans"),
        "control_test_samples": _rows(connection, "control_test_samples"),
        "control_test_results": _rows(connection, "control_test_results"),
        "remediation_plans": _rows(connection, "remediation_plans"),
        "match_jobs": _json_rows(connection, "match_jobs"),
        "match_rules": _json_rows(connection, "match_rules"),
        "match_results": _json_rows(connection, "match_results"),
        "exceptions_queue": _rows(connection, "exceptions_queue"),
        "metric_definitions": _rows(connection, "metric_definitions"),
        "metric_snapshots": _rows(connection, "metric_snapshots"),
        "ops_job_history": _rows(connection, "ops_job_history"),
        "ops_error_records": _rows(connection, "ops_error_records"),
    }


def _inventory_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "units_of_measure": _rows(connection, "units_of_measure"),
        "items": _rows(connection, "inventory_items"),
        "warehouses": _rows(connection, "warehouses"),
        "locations": _rows(connection, "inventory_locations"),
        "lots_and_serials": _rows(connection, "inventory_lots"),
        "movements": _rows(connection, "inventory_movements"),
        "movement_lines": _rows(connection, "inventory_movement_lines"),
        "count_sessions": _rows(connection, "inventory_count_sessions"),
        "count_lines": _rows(connection, "inventory_count_lines"),
        "reorder_rules": _rows(connection, "inventory_reorder_rules"),
        "valuation_policies": _rows(connection, "inventory_valuation_policies"),
        "valuation_documents": _rows(connection, "inventory_valuation_documents"),
        "valuation_input_costs": _rows(connection, "inventory_valuation_input_costs"),
        "valuation_lines": _rows(connection, "inventory_valuation_lines"),
        "cost_layers": _rows(connection, "inventory_cost_layers"),
        "layer_consumptions": _rows(connection, "inventory_layer_consumptions"),
        "valuation_reversals": _rows(connection, "inventory_valuation_reversals"),
        "valuation_reversal_effects": _rows(connection, "inventory_valuation_reversal_effects"),
    }


def build_public_export_payloads(connection: sqlite3.Connection, *, schema_version: int) -> dict[str, dict[str, Any]]:
    """Build sanitized export payloads that exclude credential and session material."""

    metadata = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "schema_version": schema_version,
        "local_first_note": "Local DB export for ReconForge migration review. No cloud upload or SaaS backup is performed.",
        "credential_material_excluded": True,
        "session_material_excluded": True,
    }
    return {
        "metadata": metadata,
        "domain": _domain_payload(connection),
        "identity": _identity_payload(connection),
        "workflow": _workflow_payload(connection),
        "audit_events": _audit_payload(connection),
        "evidence": {
            "evidence_objects": _rows(connection, "evidence_objects"),
            "evidence_registry": _rows(connection, "evidence_registry"),
            "evidence_requirements": _rows(connection, "evidence_requirements"),
            "evidence_links": _rows(connection, "evidence_links"),
        },
        "finance_workflows": _finance_payload(connection),
        "inventory": _inventory_payload(connection),
        "legacy_imports": _legacy_payload(connection),
    }


def export_database(
    db_path: Path | str,
    output_dir: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBExportResult:
    """Export sanitized local DB records to deterministic JSON files."""

    resolved_db_path = resolve_db_path(db_path)
    schema_version = _schema_version(resolved_db_path)
    connection = connect(resolved_db_path, require_exists=True)
    try:
        payloads = build_public_export_payloads(connection, schema_version=schema_version)
        resolved_output_dir = resolve_local_path(output_dir)
        if resolved_output_dir.exists() and (not resolved_output_dir.is_dir() or _path_is_reparse(resolved_output_dir)):
            raise DBBridgeError("Output path must be a local directory.")
        resolved_output_dir.parent.mkdir(parents=True, exist_ok=True)
        transaction_id = secrets.token_hex(16)
        staging_dir = resolved_output_dir.parent / f".{resolved_output_dir.name}.staging-{transaction_id}"
        staging_dir.mkdir(mode=0o700)
        try:
            staged_paths = [
                write_json_file(staging_dir / f"{name}.json", payload) for name, payload in sorted(payloads.items())
            ]
            artifacts = {
                path.name: {"bytes": path.stat().st_size, "sha256": checksum_file(path)} for path in staged_paths
            }
            write_json_file(
                staging_dir / "export_manifest.json",
                {
                    "artifact_type": "reconforge_database_export",
                    "export_format_version": EXPORT_FORMAT_VERSION,
                    "manifest_version": EXPORT_MANIFEST_VERSION,
                    "schema_version": schema_version,
                    "artifacts": artifacts,
                },
            )
            _expected_artifacts(staging_dir)
            _publish_staged_export(staging_dir, resolved_output_dir)
        finally:
            if staging_dir.exists() and not any(
                marker.name.endswith(f"{staging_dir.name.removeprefix(f'.{resolved_output_dir.name}.staging-')}.json")
                for marker in _publication_siblings(resolved_output_dir, "db-export-transaction")
            ):
                rmtree(staging_dir)
        paths = sorted(resolved_output_dir.glob("*.json"))
        append_audit_event(
            connection,
            actor_label=actor_label,
            object_type="db_bridge",
            object_id="export",
            action="db_exported",
            metadata={
                "schema_version": schema_version,
                "output_dir_name": resolved_output_dir.name,
                "file_count": len(paths),
            },
        )
    except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as exc:
        raise DBBridgeError("Unable to export local database records.") from exc
    finally:
        connection.close()
    return DBExportResult(output_dir=resolved_output_dir, paths=paths, schema_version=schema_version)
