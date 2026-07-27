"""Compatibility adapter for local operational health commands."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.application.operations import OperationsApplicationService
from reconforge.infrastructure.sqlite_operations import (
    SQLiteOperationsRepository,
    sqlite_migration_status,
)


class OperationsService:
    """Preserve the historical connection-based API over explicit ports."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._application = OperationsApplicationService(
            SQLiteOperationsRepository(connection),
            sqlite_migration_status,
        )

    def health(self, db_path: str) -> dict[str, Any]:
        return self._application.health(db_path)

    def jobs(self) -> list[dict[str, Any]]:
        return self._application.jobs()

    def errors(self) -> list[dict[str, Any]]:
        return self._application.errors()
