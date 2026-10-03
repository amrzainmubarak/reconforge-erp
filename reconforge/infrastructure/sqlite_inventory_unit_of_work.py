"""Explicit SQLite inventory ownership without changing connection semantics."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, Protocol, TypeVar

if TYPE_CHECKING:
    from reconforge.infrastructure.sqlite_inventory_core import SQLiteInventoryCoreRepository
    from reconforge.infrastructure.sqlite_inventory_valuation import SQLiteInventoryValuationRepositoryAdapter


class SQLiteInventoryUnitOfWork:
    """Own one writer transaction; explicitly bound children never finalize it.

    Catching a failed child does not make the transaction safe to commit. It stays
    rollback-only until this owner exits, including failures before business SQL.
    This is transaction composition, not a generated operational GL workflow.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.active = False
        self.rollback_only = False

    def __enter__(self) -> SQLiteInventoryUnitOfWork:
        # The legacy platform package eagerly imports the inventory adapters.
        # Resolve its compatibility exception only after this module is loaded.
        from reconforge.platform.common import PlatformError

        if self.active or self.connection.in_transaction:
            raise PlatformError("Inventory ownership requires a clean connection; pending caller work was not changed.")
        self.connection.execute("BEGIN IMMEDIATE")
        self.active = True
        self.rollback_only = False
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        from reconforge.platform.common import PlatformError

        try:
            if exc_type is not None or self.rollback_only:
                self.connection.rollback()
                if exc_type is None:
                    raise PlatformError("A failed bound operation requires rollback of the entire inventory unit of work.")
            else:
                if not self.connection.in_transaction:
                    raise PlatformError("The inventory owner transaction ended unexpectedly.")
                try:
                    self.connection.commit()
                except BaseException:
                    self.connection.rollback()
                    raise
        finally:
            self.active = False

    def require_active(self, connection: sqlite3.Connection) -> None:
        from reconforge.platform.common import PlatformError

        if connection is not self.connection:
            raise PlatformError("The inventory unit of work must own this connection.")
        if not self.active or not connection.in_transaction or self.rollback_only:
            raise PlatformError("An active inventory unit of work is required.")

    @contextmanager
    def operation(self, connection: sqlite3.Connection) -> Iterator[None]:
        self.require_active(connection)
        try:
            yield
        except BaseException:
            self.rollback_only = True
            raise

    def core(self) -> SQLiteInventoryCoreRepository:
        from reconforge.infrastructure.sqlite_inventory_core import SQLiteInventoryCoreRepository

        self.require_active(self.connection)
        return SQLiteInventoryCoreRepository(self.connection, unit_of_work=self)

    def valuation(self) -> SQLiteInventoryValuationRepositoryAdapter:
        from reconforge.infrastructure.sqlite_inventory_valuation import SQLiteInventoryValuationRepositoryAdapter

        self.require_active(self.connection)
        return SQLiteInventoryValuationRepositoryAdapter(self.connection, unit_of_work=self)


class _InventoryAdapter(Protocol):
    connection: sqlite3.Connection
    unit_of_work: SQLiteInventoryUnitOfWork | None


_Adapter = TypeVar("_Adapter", bound=_InventoryAdapter)
_Parameters = ParamSpec("_Parameters")
_Result = TypeVar("_Result")


def inventory_operation(*, write: bool = False) -> Callable[
    [Callable[Concatenate[_Adapter, _Parameters], _Result]], Callable[Concatenate[_Adapter, _Parameters], _Result]
]:
    """Check explicit participation before permission, schema or workspace helpers."""

    def decorate(method: Callable[Concatenate[_Adapter, _Parameters], _Result]) -> Callable[Concatenate[_Adapter, _Parameters], _Result]:
        @wraps(method)
        def guarded(self: _Adapter, *args: _Parameters.args, **kwargs: _Parameters.kwargs) -> _Result:
            from reconforge.platform.common import PlatformError

            if self.unit_of_work is not None:
                with self.unit_of_work.operation(self.connection):
                    return method(self, *args, **kwargs)
            if write and self.connection.in_transaction:
                raise PlatformError("Pending caller writes require an explicit inventory unit of work; caller work was not changed.")
            return method(self, *args, **kwargs)

        return guarded

    return decorate
