"""Compatibility facade for governed inventory valuation."""

from __future__ import annotations

import sqlite3

from reconforge.application.inventory_valuation import (
    InventoryValuationApplicationService,
    InventoryValuationRepositoryProtocol,
    InventoryValuationSummary,
)
from reconforge.infrastructure.sqlite_inventory_valuation import (
    INVENTORY_READ_PERMISSION,
    MAX_VALUATION_LINES,
    VALUATION_APPROVE_PERMISSION,
    VALUATION_MANAGE_PERMISSION,
    VALUATION_STATUSES,
    SQLiteInventoryValuationRepositoryAdapter,
)


class InventoryValuationService(InventoryValuationApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        repository: InventoryValuationRepositoryProtocol | None = None,
    ) -> None:
        super().__init__(repository or SQLiteInventoryValuationRepositoryAdapter(connection))

    @property
    def connection(self) -> sqlite3.Connection:
        """Retain the legacy read-only connection seam for dependent adapters."""
        repository = self.repository
        if not isinstance(repository, SQLiteInventoryValuationRepositoryAdapter):
            raise AttributeError("A non-SQLite valuation repository has no SQLite connection.")
        return repository.connection


__all__ = [
    "INVENTORY_READ_PERMISSION",
    "MAX_VALUATION_LINES",
    "VALUATION_APPROVE_PERMISSION",
    "VALUATION_MANAGE_PERMISSION",
    "VALUATION_STATUSES",
    "InventoryValuationService",
    "InventoryValuationSummary",
]
