"""Compatibility facade for local evidence-bound Accounts Payable settlement."""

from __future__ import annotations

import sqlite3

from reconforge.application.payables_payment_link import PayablesPaymentLinkApplicationService
from reconforge.infrastructure.sqlite_payables_payment_link import SQLitePayablesPaymentLinkRepository


class PayablesPaymentLinkService(PayablesPaymentLinkApplicationService):
    """Preserve the local-platform constructor while using the repository port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLitePayablesPaymentLinkRepository(connection))


__all__ = ["PayablesPaymentLinkService"]
