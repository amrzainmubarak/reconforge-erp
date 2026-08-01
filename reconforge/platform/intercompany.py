"""Compatibility facade for the backend-neutral intercompany workflow."""

from __future__ import annotations

import sqlite3

from reconforge.application.intercompany import IntercompanyApplicationService, IntercompanyImportResult
from reconforge.infrastructure.sqlite_intercompany import SQLiteIntercompanyRepository


class IntercompanyService(IntercompanyApplicationService):
    """Preserve the historical connection-based constructor."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteIntercompanyRepository(connection))


__all__ = ["IntercompanyImportResult", "IntercompanyService"]
