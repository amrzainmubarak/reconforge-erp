"""Compatibility facade for governed inventory valuation reversals."""

from __future__ import annotations

import sqlite3

from reconforge.application.inventory_valuation_reversal import (
    InventoryValuationReversalApplicationService,
    InventoryValuationReversalRepositoryProtocol,
    InventoryValuationReversalSummary,
)
from reconforge.infrastructure.sqlite_inventory_valuation_reversal import (
    REVERSAL_APPROVE_PERMISSION,
    REVERSAL_MANAGE_PERMISSION,
    REVERSAL_STATUSES,
    SQLiteInventoryValuationReversalRepositoryAdapter,
)


class InventoryValuationReversalService(InventoryValuationReversalApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(
        self, connection: sqlite3.Connection, *, repository: InventoryValuationReversalRepositoryProtocol | None = None
    ) -> None:
        super().__init__(repository or SQLiteInventoryValuationReversalRepositoryAdapter(connection))

    @property
    def connection(self) -> sqlite3.Connection:
        repository = self.repository
        if not isinstance(repository, SQLiteInventoryValuationReversalRepositoryAdapter):
            raise AttributeError("A non-SQLite reversal repository has no SQLite connection.")
        return repository.connection


__all__ = [
    "REVERSAL_APPROVE_PERMISSION",
    "REVERSAL_MANAGE_PERMISSION",
    "REVERSAL_STATUSES",
    "InventoryValuationReversalService",
    "InventoryValuationReversalSummary",
]
