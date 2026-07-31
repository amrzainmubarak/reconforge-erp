"""Compatibility facade for backend-neutral close management."""

from __future__ import annotations

import sqlite3

from reconforge.application.close import CloseManagementApplicationService, CloseReadiness
from reconforge.infrastructure.sqlite_close import SQLiteCloseManagementRepository


class CloseManagementService(CloseManagementApplicationService):
    """Preserve the historical connection-based constructor."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteCloseManagementRepository(connection))


__all__ = ["CloseManagementService", "CloseReadiness"]
