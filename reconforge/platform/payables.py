"""Compatibility facade for the governed purchase-to-pay boundary."""

from __future__ import annotations

import sqlite3

from reconforge.application.payables import (
    PayablesApplicationService,
    PurchaseOrderLineInput,
    SupplierInvoiceLineInput,
    ThreeWayMatchResult,
)
from reconforge.infrastructure.sqlite_payables import SQLitePayablesRepository


class PayablesService(PayablesApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLitePayablesRepository(connection))


__all__ = [
    "PayablesService",
    "PurchaseOrderLineInput",
    "SupplierInvoiceLineInput",
    "ThreeWayMatchResult",
]
