"""Local operations and health helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.audit import AuditLedgerError, verify_audit_events
from reconforge.db import database_status
from reconforge.platform.common import ensure_platform_schema, rows_to_dicts


class OperationsService:
    """Read local operational health without dumping finance rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def health(self, db_path: str) -> dict[str, Any]:
        """Return sanitized local health status."""

        status = database_status(db_path)
        try:
            audit_ok = verify_audit_events(self.connection).ok
        except AuditLedgerError:
            audit_ok = False
        errors = self.connection.execute("SELECT COUNT(*) AS count FROM ops_error_records").fetchone()
        jobs = self.connection.execute("SELECT COUNT(*) AS count FROM ops_job_history").fetchone()
        return {
            "database_reachable": True,
            "schema_version": status.current_version,
            "latest_schema_version": status.latest_version,
            "pending_migrations": len(status.pending_versions),
            "audit_chain_ok": audit_ok,
            "job_records": int(jobs["count"] or 0),
            "error_records": int(errors["count"] or 0),
            "local_only": True,
        }

    def jobs(self) -> list[dict[str, Any]]:
        """List local job history summaries."""

        return rows_to_dicts(self.connection.execute("SELECT * FROM ops_job_history ORDER BY started_at DESC").fetchall())

    def errors(self) -> list[dict[str, Any]]:
        """List sanitized local error records."""

        return rows_to_dicts(self.connection.execute("SELECT * FROM ops_error_records ORDER BY created_at DESC").fetchall())
