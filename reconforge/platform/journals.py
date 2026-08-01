"""Compatibility facade for backend-neutral journal controls."""

from __future__ import annotations

import sqlite3

from reconforge.application.journals import JournalControlApplicationService
from reconforge.application.journals import JournalImportResult as JournalImportResult
from reconforge.infrastructure.sqlite_journals import SQLiteJournalControlRepository


class JournalControlService(JournalControlApplicationService):
    """Preserve the historical connection-based API without owning SQL."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        super().__init__(SQLiteJournalControlRepository(connection))
