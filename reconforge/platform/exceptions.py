"""Compatibility facade for the backend-neutral exception queue service."""

from __future__ import annotations

import sqlite3

from reconforge.application.exceptions import ExceptionQueueApplicationService
from reconforge.infrastructure.sqlite_exceptions import EXCEPTION_STATUSES as EXCEPTION_STATUSES
from reconforge.infrastructure.sqlite_exceptions import SQLiteExceptionQueueRepository


class ExceptionQueueService(ExceptionQueueApplicationService):
    """Preserve the historical connection-based local API without owning SQL."""

    def __init__(self, connection: sqlite3.Connection, *, autocommit: bool = True) -> None:
        self.connection = connection
        self.autocommit = autocommit
        super().__init__(SQLiteExceptionQueueRepository(connection, autocommit=autocommit))
