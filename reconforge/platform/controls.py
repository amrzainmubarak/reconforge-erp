"""Compatibility facade for backend-neutral control testing."""

from __future__ import annotations

import sqlite3

from reconforge.application.controls import ControlLibraryImportResult as ControlLibraryImportResult
from reconforge.application.controls import ControlTestingApplicationService
from reconforge.infrastructure.sqlite_controls import SQLiteControlTestingRepository


class ControlTestingService(ControlTestingApplicationService):
    """Preserve the historical connection-based API without owning SQL."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        super().__init__(SQLiteControlTestingRepository(connection))
