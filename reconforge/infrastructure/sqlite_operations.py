"""SQLite adapter for backend-neutral operational diagnostics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from reconforge.application.operations import MigrationStatus
from reconforge.audit import AuditLedgerError, verify_audit_events
from reconforge.db import database_status
from reconforge.platform.common import ensure_platform_schema


@dataclass
class SQLiteOperationsRepository:
    """Read sanitized operational state from a caller-owned connection."""

    connection: sqlite3.Connection

    def __post_init__(self) -> None:
        ensure_platform_schema(self.connection)

    def audit_chain_ok(self) -> bool:
        try:
            return verify_audit_events(self.connection).ok
        except AuditLedgerError:
            return False

    def record_counts(self) -> tuple[int, int]:
        jobs = self.connection.execute("SELECT COUNT(*) AS count FROM ops_job_history").fetchone()
        errors = self.connection.execute("SELECT COUNT(*) AS count FROM ops_error_records").fetchone()
        return int(jobs["count"] or 0), int(errors["count"] or 0)

    def list_jobs(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM ops_job_history ORDER BY started_at DESC").fetchall()
        return [dict(row) for row in rows]

    def list_errors(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM ops_error_records ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def sqlite_migration_status(database_locator: str) -> MigrationStatus:
    """Adapt the existing local migration status contract."""

    status = database_status(database_locator)
    return MigrationStatus(
        current_version=status.current_version,
        latest_version=status.latest_version,
        pending_versions=tuple(status.pending_versions),
    )
