"""Compatibility facade for the governed accounts-receivable boundary."""

from __future__ import annotations

import sqlite3

from reconforge.application.receivables import (
    ReceiptAllocationInput,
    ReceivableInvoiceLineInput,
    ReceivablesApplicationService,
)
from reconforge.infrastructure.sqlite_receivables import SQLiteReceivablesRepository


class ReceivablesService(ReceivablesApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteReceivablesRepository(connection))


__all__ = [
    "ReceiptAllocationInput",
    "ReceivableInvoiceLineInput",
    "ReceivablesService",
]
