"""SQLite unit-of-work adapter for backend-neutral application services."""

from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Literal

from reconforge.domain.protocols import DomainUnitOfWorkProtocol
from reconforge.domain.repositories import AuditEventRepository, PeriodRepository, WorkspaceRepository


class SQLiteUnitOfWorkError(RuntimeError):
    """Raised when transaction ownership or lifecycle is invalid."""


class SQLiteDomainUnitOfWork(DomainUnitOfWorkProtocol):
    """Own one fail-closed SQLite transaction across domain repositories."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.workspaces = WorkspaceRepository(connection, autocommit=False)
        self.periods = PeriodRepository(connection, autocommit=False)
        self.audit_events = AuditEventRepository(connection)
        self._active = False
        self._committed = False

    def __enter__(self) -> SQLiteDomainUnitOfWork:
        if self._active or self._connection.in_transaction:
            raise SQLiteUnitOfWorkError("SQLite unit of work requires exclusive transaction ownership.")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except sqlite3.DatabaseError as exc:
            raise SQLiteUnitOfWorkError("Unable to begin the SQLite unit of work.") from exc
        self._active = True
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if self._active:
            if exc_type is not None or not self._committed:
                self.rollback()
            else:
                self._active = False
        return False

    def commit(self) -> None:
        if not self._active:
            raise SQLiteUnitOfWorkError("SQLite unit of work is not active.")
        try:
            self._connection.commit()
        except sqlite3.DatabaseError as exc:
            self._connection.rollback()
            self._active = False
            raise SQLiteUnitOfWorkError("Unable to commit the SQLite unit of work.") from exc
        self._committed = True
        self._active = False

    def rollback(self) -> None:
        if not self._active:
            return
        try:
            self._connection.rollback()
        except sqlite3.DatabaseError as exc:
            self._active = False
            raise SQLiteUnitOfWorkError("Unable to roll back the SQLite unit of work.") from exc
        self._active = False
        self._committed = False
