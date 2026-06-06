"""Local DB backup and restore helpers for the migration bridge."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconforge.audit import append_audit_event
from reconforge.db.connection import connect, resolve_db_path
from reconforge.db.exporter import (
    DBBridgeError,
    checksum_file,
    resolve_input_file,
    resolve_local_path,
    resolve_output_dir,
    write_json_file,
)
from reconforge.db.migrations import MIGRATIONS, database_status, run_migrations
from reconforge.domain.models import utc_now_text

BACKUP_FORMAT_VERSION = 1
BACKUP_WARNING = (
    "ReconForge local DB backups may contain sensitive local business data and local password hashes "
    "needed for restore. Protect backup files. This is not cloud backup, SaaS storage, an enterprise "
    "DR guarantee, or a compliance certification."
)

BACKUP_TABLES = [
    "schema_migrations",
    "workspaces",
    "organizations",
    "legal_entities",
    "periods",
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "accounts",
    "reconciliations",
    "tasks",
    "controls",
    "evidence_objects",
    "workflow_objects",
    "workflow_transitions",
    "workflow_transition_events",
    "legacy_import_records",
    "audit_events",
    "audit_ledger_state",
]

EXCLUDED_BACKUP_TABLES = ["api_sessions"]

BACKUP_SELECT_QUERIES = {
    "schema_migrations": "SELECT * FROM schema_migrations ORDER BY version",
    "workspaces": "SELECT * FROM workspaces ORDER BY created_at, id",
    "organizations": "SELECT * FROM organizations ORDER BY created_at, id",
    "legal_entities": "SELECT * FROM legal_entities ORDER BY entity_code, id",
    "periods": "SELECT * FROM periods ORDER BY start_date, id",
    "users": "SELECT * FROM users ORDER BY username",
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
    "legacy_import_records": "SELECT * FROM legacy_import_records ORDER BY source_type, object_type, object_id",
    "audit_events": "SELECT * FROM audit_events ORDER BY sequence",
    "audit_ledger_state": "SELECT * FROM audit_ledger_state ORDER BY id",
}

BACKUP_DELETE_QUERIES = {
    "schema_migrations": "DELETE FROM schema_migrations",
    "workspaces": "DELETE FROM workspaces",
    "organizations": "DELETE FROM organizations",
    "legal_entities": "DELETE FROM legal_entities",
    "periods": "DELETE FROM periods",
    "users": "DELETE FROM users",
    "roles": "DELETE FROM roles",
    "permissions": "DELETE FROM permissions",
    "user_roles": "DELETE FROM user_roles",
    "role_permissions": "DELETE FROM role_permissions",
    "accounts": "DELETE FROM accounts",
    "reconciliations": "DELETE FROM reconciliations",
    "tasks": "DELETE FROM tasks",
    "controls": "DELETE FROM controls",
    "evidence_objects": "DELETE FROM evidence_objects",
    "workflow_objects": "DELETE FROM workflow_objects",
    "workflow_transitions": "DELETE FROM workflow_transitions",
    "workflow_transition_events": "DELETE FROM workflow_transition_events",
    "legacy_import_records": "DELETE FROM legacy_import_records",
    "audit_events": "DELETE FROM audit_events",
    "audit_ledger_state": "DELETE FROM audit_ledger_state",
}

BACKUP_INSERT_COLUMNS = {
    "schema_migrations": ("version", "name", "applied_at"),
    "workspaces": ("id", "name", "local_first_note", "created_at"),
    "organizations": ("id", "workspace_id", "name", "created_at"),
    "legal_entities": ("id", "organization_id", "entity_code", "name", "currency", "created_at"),
    "periods": ("id", "workspace_id", "name", "start_date", "end_date", "status", "created_at"),
    "users": (
        "id",
        "username",
        "display_name",
        "email",
        "disabled",
        "created_at",
        "password_hash",
        "password_salt",
        "password_iterations",
        "password_algorithm",
        "password_changed_at",
        "failed_login_count",
        "locked_until",
    ),
    "roles": ("id", "name"),
    "permissions": ("name", "description"),
    "user_roles": ("user_id", "role_id"),
    "role_permissions": ("role_id", "permission_name"),
    "accounts": ("id", "workspace_id", "account_code", "account_name", "created_at"),
    "reconciliations": ("id", "workspace_id", "period_id", "account_id", "reconciliation_type", "status", "owner_user_id", "created_at"),
    "tasks": ("id", "workspace_id", "period_id", "task_type", "status", "owner_user_id", "created_at"),
    "controls": ("id", "workspace_id", "control_code", "name", "status", "owner_user_id", "created_at"),
    "evidence_objects": ("id", "workspace_id", "source_path", "checksum_sha256", "provenance_type", "redaction_status", "created_at"),
    "workflow_objects": ("object_type", "object_id", "status", "updated_at", "id", "created_at"),
    "workflow_transitions": ("id", "object_type", "from_status", "to_status", "required_permission", "sod_rule", "reason_required", "active"),
    "workflow_transition_events": ("id", "workflow_object_id", "from_status", "to_status", "actor_user_id", "actor_label", "reason", "created_at"),
    "legacy_import_records": (
        "id",
        "source_type",
        "object_type",
        "object_id",
        "status",
        "source_path",
        "source_checksum_sha256",
        "summary_json",
        "imported_at",
    ),
    "audit_events": (
        "id",
        "sequence",
        "previous_hash",
        "event_hash",
        "actor_user_id",
        "actor_label",
        "object_type",
        "object_id",
        "action",
        "before_hash",
        "after_hash",
        "metadata_json",
        "created_at",
    ),
    "audit_ledger_state": ("id", "last_sequence", "last_event_hash", "updated_at"),
}

BACKUP_INSERT_QUERIES = {
    "schema_migrations": "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
    "workspaces": "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES (?, ?, ?, ?)",
    "organizations": "INSERT INTO organizations (id, workspace_id, name, created_at) VALUES (?, ?, ?, ?)",
    "legal_entities": "INSERT INTO legal_entities (id, organization_id, entity_code, name, currency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    "periods": "INSERT INTO periods (id, workspace_id, name, start_date, end_date, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "users": """
        INSERT INTO users (
            id, username, display_name, email, disabled, created_at,
            password_hash, password_salt, password_iterations, password_algorithm,
            password_changed_at, failed_login_count, locked_until
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "roles": "INSERT INTO roles (id, name) VALUES (?, ?)",
    "permissions": "INSERT INTO permissions (name, description) VALUES (?, ?)",
    "user_roles": "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
    "role_permissions": "INSERT INTO role_permissions (role_id, permission_name) VALUES (?, ?)",
    "accounts": "INSERT INTO accounts (id, workspace_id, account_code, account_name, created_at) VALUES (?, ?, ?, ?, ?)",
    "reconciliations": """
        INSERT INTO reconciliations (
            id, workspace_id, period_id, account_id, reconciliation_type,
            status, owner_user_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "tasks": "INSERT INTO tasks (id, workspace_id, period_id, task_type, status, owner_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "controls": "INSERT INTO controls (id, workspace_id, control_code, name, status, owner_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "evidence_objects": """
        INSERT INTO evidence_objects (
            id, workspace_id, source_path, checksum_sha256, provenance_type,
            redaction_status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "workflow_objects": "INSERT INTO workflow_objects (object_type, object_id, status, updated_at, id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    "workflow_transitions": """
        INSERT INTO workflow_transitions (
            id, object_type, from_status, to_status, required_permission,
            sod_rule, reason_required, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "workflow_transition_events": """
        INSERT INTO workflow_transition_events (
            id, workflow_object_id, from_status, to_status,
            actor_user_id, actor_label, reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "legacy_import_records": """
        INSERT INTO legacy_import_records (
            id, source_type, object_type, object_id, status, source_path,
            source_checksum_sha256, summary_json, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "audit_events": """
        INSERT INTO audit_events (
            id, sequence, previous_hash, event_hash, actor_user_id, actor_label,
            object_type, object_id, action, before_hash, after_hash, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "audit_ledger_state": "INSERT INTO audit_ledger_state (id, last_sequence, last_event_hash, updated_at) VALUES (?, ?, ?, ?)",
}


@dataclass(frozen=True)
class DBBackupResult:
    """Files written for one local DB backup."""

    output_dir: Path
    backup_path: Path
    manifest_path: Path
    checksum_sha256: str
    schema_version: int


@dataclass(frozen=True)
class DBRestoreResult:
    """Result from one local DB restore."""

    db_path: Path
    backup_path: Path
    schema_version: int
    restored_tables: list[str]


def _schema_version(db_path: Path | str) -> int:
    status = database_status(db_path)
    if status.pending_versions:
        raise DBBridgeError("ReconForge database has pending migrations. Run 'reconforge db migrate' first.")
    return status.current_version


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(connection, table):
        return []
    query = BACKUP_SELECT_QUERIES.get(table)
    if query is None:
        raise DBBridgeError("Unsupported backup table.")
    rows = connection.execute(query).fetchall()
    return [dict(row) for row in rows]


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DBBridgeError("Backup JSON could not be parsed.") from exc
    if not isinstance(payload, dict):
        raise DBBridgeError("Backup JSON must contain an object.")
    return payload


def _backup_payload(connection: sqlite3.Connection, *, created_at: str, schema_version: int) -> dict[str, Any]:
    return {
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": created_at,
        "schema_version": schema_version,
        "latest_supported_schema_version": MIGRATIONS[-1].version,
        "privacy_warning": BACKUP_WARNING,
        "restore_sensitive_material": "Includes local credential verifier fields needed for restore.",
        "excluded_tables": EXCLUDED_BACKUP_TABLES,
        "tables": {table: _table_rows(connection, table) for table in BACKUP_TABLES},
    }


def create_backup(
    db_path: Path | str,
    output_dir: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBBackupResult:
    """Create a local JSON backup and checksum manifest."""

    resolved_db_path = resolve_db_path(db_path)
    schema_version = _schema_version(resolved_db_path)
    resolved_output_dir = resolve_output_dir(output_dir)
    created_at = utc_now_text()
    backup_path = resolved_output_dir / "backup.json"
    manifest_path = resolved_output_dir / "manifest.json"
    connection = connect(resolved_db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label=actor_label,
            object_type="db_bridge",
            object_id="backup",
            action="db_backup_created",
            metadata={
                "schema_version": schema_version,
                "backup_dir_name": resolved_output_dir.name,
                "excluded_tables": EXCLUDED_BACKUP_TABLES,
            },
        )
        payload = _backup_payload(connection, created_at=created_at, schema_version=schema_version)
        write_json_file(backup_path, payload)
        checksum = checksum_file(backup_path)
        manifest = {
            "manifest_version": 1,
            "created_at": created_at,
            "schema_version": schema_version,
            "privacy_warning": BACKUP_WARNING,
            "artifacts": {
                "backup.json": {
                    "sha256": checksum,
                    "bytes": backup_path.stat().st_size,
                },
            },
        }
        write_json_file(manifest_path, manifest)
    except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as exc:
        raise DBBridgeError("Unable to create local DB backup.") from exc
    finally:
        connection.close()
    return DBBackupResult(
        output_dir=resolved_output_dir,
        backup_path=backup_path,
        manifest_path=manifest_path,
        checksum_sha256=checksum,
        schema_version=schema_version,
    )


def _backup_paths(input_path: Path | str) -> tuple[Path, Path]:
    resolved = resolve_local_path(input_path)
    backup_path = resolved / "backup.json" if resolved.is_dir() else resolve_input_file(resolved)
    manifest_path = backup_path.parent / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        raise DBBridgeError("Backup manifest not found.")
    return backup_path, manifest_path


def _validate_backup(input_path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    backup_path, manifest_path = _backup_paths(input_path)
    manifest = _read_json_file(manifest_path)
    backup = _read_json_file(backup_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get("backup.json"), dict):
        raise DBBridgeError("Backup manifest is invalid.")
    expected_checksum = str(artifacts["backup.json"].get("sha256", ""))
    actual_checksum = checksum_file(backup_path)
    if not expected_checksum or actual_checksum != expected_checksum:
        raise DBBridgeError("Backup checksum verification failed.")
    format_version = int(backup.get("backup_format_version", 0))
    if format_version != BACKUP_FORMAT_VERSION:
        raise DBBridgeError("Unsupported backup format version.")
    schema_version = int(backup.get("schema_version", 0))
    if schema_version <= 0 or schema_version > MIGRATIONS[-1].version:
        raise DBBridgeError("Unsupported backup schema version.")
    if not isinstance(backup.get("tables"), dict):
        raise DBBridgeError("Backup table payload is invalid.")
    return backup_path, manifest, backup


def _temp_restore_path(target: Path) -> Path:
    return target.with_name(f"{target.stem}.restore_tmp{target.suffix}")


def _clear_restore_tables(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    for table in reversed(BACKUP_TABLES):
        if _table_exists(connection, table):
            query = BACKUP_DELETE_QUERIES.get(table)
            if query is None:
                raise DBBridgeError("Unsupported restore table.")
            connection.execute(query)
    if _table_exists(connection, "sqlite_sequence"):
        connection.execute("DELETE FROM sqlite_sequence")
    connection.commit()


def _insert_rows(connection: sqlite3.Connection, *, table: str, rows: object) -> None:
    if rows is None:
        return
    if not isinstance(rows, list):
        raise DBBridgeError("Backup table rows are invalid.")
    if not _table_exists(connection, table):
        raise DBBridgeError(f"Backup table is not supported by this ReconForge version: {table}.")
    columns = BACKUP_INSERT_COLUMNS.get(table)
    query = BACKUP_INSERT_QUERIES.get(table)
    if columns is None or query is None:
        raise DBBridgeError("Unsupported restore table.")
    for row in rows:
        if not isinstance(row, dict):
            raise DBBridgeError("Backup table row is invalid.")
        if not row:
            continue
        unknown_columns = set(row) - set(columns)
        if unknown_columns:
            raise DBBridgeError(f"Backup table contains unsupported columns: {table}.")
        values = [row.get(column) for column in columns]
        connection.execute(query, values)


def restore_backup(
    db_path: Path | str,
    input_path: Path | str,
    *,
    force: bool = False,
    actor_label: str = "local-cli",
) -> DBRestoreResult:
    """Restore a local DB backup after checksum validation."""

    backup_path, _manifest, backup = _validate_backup(input_path)
    target = resolve_db_path(db_path)
    if target.exists() and not force:
        raise DBBridgeError("Restore target already exists. Re-run with --force to overwrite it.")
    temp_path = _temp_restore_path(target)
    if temp_path.exists():
        if temp_path.is_symlink():
            raise DBBridgeError("Unsafe temporary restore path.")
        temp_path.unlink()
    restored_tables: list[str] = []
    try:
        run_migrations(temp_path)
        connection = connect(temp_path, require_exists=True)
        try:
            _clear_restore_tables(connection)
            tables = backup["tables"]
            if not isinstance(tables, dict):
                raise DBBridgeError("Backup table payload is invalid.")
            for table in BACKUP_TABLES:
                _insert_rows(connection, table=table, rows=tables.get(table, []))
                restored_tables.append(table)
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
            append_audit_event(
                connection,
                actor_label=actor_label,
                object_type="db_bridge",
                object_id="restore",
                action="db_backup_restored",
                metadata={
                    "backup_file": backup_path.name,
                    "schema_version": int(backup["schema_version"]),
                    "restored_table_count": len(restored_tables),
                },
            )
        finally:
            connection.close()
        temp_path.replace(target)
    except DBBridgeError:
        if temp_path.exists():
            temp_path.unlink()
        raise
    except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as exc:
        if temp_path.exists():
            temp_path.unlink()
        raise DBBridgeError("Unable to restore local DB backup.") from exc
    return DBRestoreResult(
        db_path=target,
        backup_path=backup_path,
        schema_version=int(backup["schema_version"]),
        restored_tables=restored_tables,
    )
