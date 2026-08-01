"""Compatibility facade for governed master-data services."""

from __future__ import annotations

import sqlite3

from reconforge.application.master_data import DEFAULT_LIST_LIMIT, MasterDataApplicationService, MasterDataSummary
from reconforge.infrastructure.sqlite_master_data import SQLiteMasterDataRepository


class MasterDataService(MasterDataApplicationService):
    """Backward-compatible SQLite composition root."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteMasterDataRepository(connection))


__all__ = ["DEFAULT_LIST_LIMIT", "MasterDataService", "MasterDataSummary"]
