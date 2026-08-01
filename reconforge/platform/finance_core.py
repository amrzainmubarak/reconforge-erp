"""Compatibility facade for the governed finance-core application boundary."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any, cast

from reconforge.application.finance_core import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    FinanceCoreApplicationService,
    FinanceCoreSummary,
)
from reconforge.infrastructure.sqlite_finance_core import SQLiteFinanceCoreRepository


class FinanceCoreService(FinanceCoreApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteFinanceCoreRepository(connection))

    @property
    def _validate_entry_integrity(self) -> Callable[[dict[str, Any]], None]:
        """Retain the historical atomicity-test seam during strangler migration."""

        repository = cast(SQLiteFinanceCoreRepository, self.repository)
        return repository._validate_entry_integrity

    @_validate_entry_integrity.setter
    def _validate_entry_integrity(self, validator: Callable[[dict[str, Any]], None]) -> None:
        repository = cast(SQLiteFinanceCoreRepository, self.repository)
        repository._validate_entry_integrity = validator  # type: ignore[method-assign,assignment]


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "FinanceCoreService",
    "FinanceCoreSummary",
]
