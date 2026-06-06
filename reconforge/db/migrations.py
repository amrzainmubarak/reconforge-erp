"""SQLite migration runner for local ReconForge databases."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reconforge.db.connection import DatabaseError, connect, resolve_db_path
from reconforge.db.schema import AUTH_RBAC_SCHEMA_SQL, INITIAL_SCHEMA_SQL


@dataclass(frozen=True)
class Migration:
    """One local SQLite schema migration."""

    version: int
    name: str
    sql: str


@dataclass(frozen=True)
class MigrationStatus:
    """Result from applying migrations."""

    path: Path
    applied_versions: list[int]
    current_version: int
    latest_version: int


@dataclass(frozen=True)
class DatabaseStatus:
    """Current local database schema state."""

    path: Path
    current_version: int
    latest_version: int
    applied_versions: list[int]
    pending_versions: list[int]


MIGRATIONS = [
    Migration(version=1, name="enterprise_domain_and_audit_foundation", sql=INITIAL_SCHEMA_SQL),
    Migration(version=2, name="local_users_rbac_foundation", sql=AUTH_RBAC_SCHEMA_SQL),
]

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(_MIGRATION_TABLE_SQL)
    connection.commit()


def _applied_versions(connection: sqlite3.Connection) -> list[int]:
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row["version"]) for row in rows]


def run_migrations(db_path: Path | str) -> MigrationStatus:
    """Create or migrate a local ReconForge SQLite database."""

    resolved = resolve_db_path(db_path)
    connection = connect(resolved, create_parent=True)
    applied_now: list[int] = []
    try:
        _ensure_migration_table(connection)
        already_applied = set(_applied_versions(connection))
        for migration in MIGRATIONS:
            if migration.version in already_applied:
                continue
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, _utc_now()),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
            applied_now.append(migration.version)
        applied = _applied_versions(connection)
        current_version = max(applied, default=0)
    except sqlite3.DatabaseError as exc:
        connection.rollback()
        raise DatabaseError("Unable to migrate ReconForge database. The file may not be a valid local SQLite database.") from exc
    finally:
        connection.close()

    return MigrationStatus(
        path=resolved,
        applied_versions=applied_now,
        current_version=current_version,
        latest_version=MIGRATIONS[-1].version,
    )


def database_status(db_path: Path | str) -> DatabaseStatus:
    """Return schema status for an existing local ReconForge database."""

    resolved = resolve_db_path(db_path)
    connection = connect(resolved, require_exists=True)
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'",
        ).fetchone()
        applied = _applied_versions(connection) if table_exists else []
        current_version = max(applied, default=0)
    except sqlite3.DatabaseError as exc:
        raise DatabaseError("Unable to read ReconForge database. The file may not be a valid local SQLite database.") from exc
    finally:
        connection.close()

    latest = MIGRATIONS[-1].version
    pending = [migration.version for migration in MIGRATIONS if migration.version not in set(applied)]
    return DatabaseStatus(
        path=resolved,
        current_version=current_version,
        latest_version=latest,
        applied_versions=applied,
        pending_versions=pending,
    )
