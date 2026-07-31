"""Compatibility facade for backend-neutral account reconciliation."""

from __future__ import annotations

import sqlite3

from reconforge.application.accounts import (
    AccountReconciliationApplicationService,
    ImportTrialBalanceResult,
)
from reconforge.infrastructure.sqlite_accounts import SQLiteAccountReconciliationRepository


class AccountReconciliationService(AccountReconciliationApplicationService):
    """Preserve the historical connection-based constructor."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteAccountReconciliationRepository(connection))


__all__ = ["AccountReconciliationService", "ImportTrialBalanceResult"]
