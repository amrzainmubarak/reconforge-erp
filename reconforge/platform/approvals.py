"""Compatibility facade for approval and certification workflows."""

from __future__ import annotations

import sqlite3

from reconforge.application.approvals import ApprovalApplicationService
from reconforge.infrastructure.sqlite_approvals import SQLiteApprovalRepository


class ApprovalService(ApprovalApplicationService):
    """Preserve the historical connection-based API without owning SQL."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        super().__init__(SQLiteApprovalRepository(connection))
