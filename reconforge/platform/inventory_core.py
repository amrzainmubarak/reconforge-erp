"""Compatibility facade for the governed inventory-core application boundary."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import cast

from reconforge.application.inventory_core import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    InventoryCoreApplicationService,
    InventoryCoreSummary,
)
from reconforge.infrastructure.sqlite_inventory_core import SQLiteInventoryCoreRepository


class InventoryCoreService(InventoryCoreApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteInventoryCoreRepository(connection))

    @property
    def connection(self) -> sqlite3.Connection:
        """Retain the historical connection test seam during extraction."""

        repository = cast(SQLiteInventoryCoreRepository, self.repository)
        return repository.connection

    @connection.setter
    def connection(self, connection: sqlite3.Connection) -> None:
        repository = cast(SQLiteInventoryCoreRepository, self.repository)
        repository.connection = connection

    @property
    def on_hand(self) -> Callable[..., dict[str, object]]:
        """Retain internal balance-read fault-injection compatibility."""

        repository = cast(SQLiteInventoryCoreRepository, self.repository)
        return repository.on_hand

    @on_hand.setter
    def on_hand(self, reader: Callable[..., dict[str, object]]) -> None:
        repository = cast(SQLiteInventoryCoreRepository, self.repository)
        repository.on_hand = reader  # type: ignore[method-assign]

    @property
    def _validate_movement_integrity(self) -> Callable[..., None]:
        """Retain the historical transaction/integrity test seam."""

        repository = cast(SQLiteInventoryCoreRepository, self.repository)
        return repository._validate_movement_integrity

    @_validate_movement_integrity.setter
    def _validate_movement_integrity(self, validator: Callable[..., None]) -> None:
        repository = cast(SQLiteInventoryCoreRepository, self.repository)
        repository._validate_movement_integrity = validator  # type: ignore[method-assign]


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "InventoryCoreService",
    "InventoryCoreSummary",
]
