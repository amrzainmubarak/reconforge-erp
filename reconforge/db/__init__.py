"""Local SQLite database foundation for ReconForge ERP."""

from __future__ import annotations

from reconforge.db.connection import DatabaseError, DatabasePathError, connect, resolve_db_path
from reconforge.db.migrations import DatabaseStatus, MigrationStatus, database_status, run_migrations

__all__ = [
    "DatabaseError",
    "DatabasePathError",
    "DatabaseStatus",
    "MigrationStatus",
    "connect",
    "database_status",
    "resolve_db_path",
    "run_migrations",
]
