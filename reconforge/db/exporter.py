"""Safe local DB export helpers for the migration bridge."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from reconforge.audit import append_audit_event
from reconforge.db.connection import connect, resolve_db_path
from reconforge.db.migrations import database_status

EXPORT_FORMAT_VERSION = 1

SELECT_QUERIES = {
    "workspaces": "SELECT * FROM workspaces ORDER BY created_at, id",
    "organizations": "SELECT * FROM organizations ORDER BY created_at, id",
    "legal_entities": "SELECT * FROM legal_entities ORDER BY entity_code, id",
    "periods": "SELECT * FROM periods ORDER BY start_date, id",
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


class DBBridgeError(ValueError):
    """Raised for safe, user-facing DB bridge errors."""


@dataclass(frozen=True)
class DBExportResult:
    """Files written by the local DB export bridge."""

    output_dir: Path
    paths: list[Path]
    schema_version: int


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


def _json_rows(connection: sqlite3.Connection, table: str, *, json_columns: set[str]) -> list[dict[str, Any]]:
    records = _rows(connection, table)
    for record in records:
        for column in json_columns:
            value = record.get(column)
            if isinstance(value, str):
                try:
                    record[column.removesuffix("_json")] = json.loads(value)
                except json.JSONDecodeError:
                    record[column.removesuffix("_json")] = {"invalid_json": True}
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
        "legal_entities": _rows(connection, "legal_entities"),
        "periods": _rows(connection, "periods"),
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
        "audit_events": _json_rows(connection, "audit_events", json_columns={"metadata_json"}),
    }


def _legacy_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "legacy_import_records": _json_rows(
            connection,
            "legacy_import_records",
            json_columns={"summary_json"},
        ),
    }


def _finance_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
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
        "match_jobs": _json_rows(connection, "match_jobs", json_columns={"rule_json"}),
        "match_rules": _json_rows(connection, "match_rules", json_columns={"rule_json"}),
        "match_results": _rows(connection, "match_results"),
        "exceptions_queue": _rows(connection, "exceptions_queue"),
        "metric_definitions": _rows(connection, "metric_definitions"),
        "metric_snapshots": _rows(connection, "metric_snapshots"),
        "ops_job_history": _rows(connection, "ops_job_history"),
        "ops_error_records": _rows(connection, "ops_error_records"),
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
    resolved_output_dir = resolve_output_dir(output_dir)
    connection = connect(resolved_db_path, require_exists=True)
    try:
        payloads = build_public_export_payloads(connection, schema_version=schema_version)
        paths = [
            write_json_file(resolved_output_dir / f"{name}.json", payload)
            for name, payload in sorted(payloads.items())
        ]
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
