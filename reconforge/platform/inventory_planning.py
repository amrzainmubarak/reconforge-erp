"""Compatibility facade for governed inventory planning."""

from __future__ import annotations

import sqlite3
from typing import cast

from reconforge.application.inventory_planning import (
    InventoryPlanningApplicationService,
    InventoryPlanningRepositoryProtocol,
    InventoryPlanningSummary,
)
from reconforge.infrastructure.sqlite_inventory_planning import (
    COUNT_APPROVE_PERMISSION,
    COUNT_MANAGE_PERMISSION,
    COUNT_STATUSES,
    INVENTORY_READ_PERMISSION,
    MAX_COUNT_LINES,
    REORDER_MANAGE_PERMISSION,
    SQLiteInventoryPlanningRepositoryAdapter,
)
from reconforge.infrastructure.sqlite_inventory_planning_repository import InventoryPlanningRepository
from reconforge.platform.inventory_values import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT


class InventoryPlanningService(InventoryPlanningApplicationService):
    def __init__(
        self, connection: sqlite3.Connection, *, repository: InventoryPlanningRepository | None = None
    ) -> None:
        adapter = SQLiteInventoryPlanningRepositoryAdapter(connection, repository=repository)
        super().__init__(cast(InventoryPlanningRepositoryProtocol, adapter))

    @property
    def connection(self) -> sqlite3.Connection:
        if not isinstance(self.repository, SQLiteInventoryPlanningRepositoryAdapter):
            raise AttributeError("A non-SQLite planning repository has no SQLite connection.")
        return self.repository.connection


__all__ = [
    "COUNT_APPROVE_PERMISSION",
    "COUNT_MANAGE_PERMISSION",
    "COUNT_STATUSES",
    "DEFAULT_LIST_LIMIT",
    "INVENTORY_READ_PERMISSION",
    "MAX_COUNT_LINES",
    "MAX_LIST_LIMIT",
    "REORDER_MANAGE_PERMISSION",
    "InventoryPlanningService",
    "InventoryPlanningSummary",
]
