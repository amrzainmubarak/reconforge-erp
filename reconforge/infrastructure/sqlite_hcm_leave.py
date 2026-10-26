"""SQLite persistence repository for HCM Employee Leave and Entitlements."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import cast

from reconforge.audit import append_audit_event
from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveCategory,
    LeaveEntitlementBalance,
    LeaveRequest,
    LeaveStatus,
)

CREATE_HCM_LEAVE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS hcm_employee_identities (
    workspace_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (workspace_id, employee_id)
);

CREATE TABLE IF NOT EXISTS hcm_leave_entitlement_balances (
    workspace_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    annual_entitlement_days INTEGER NOT NULL,
    accrued_days INTEGER NOT NULL,
    consumed_days INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, employee_id, leave_type)
);

CREATE TABLE IF NOT EXISTS hcm_leave_requests (
    workspace_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_user_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    requested_days INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    approved_by_user_id TEXT,
    rejection_reason TEXT,
    PRIMARY KEY (workspace_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_hcm_leave_requests_employee
ON hcm_leave_requests (workspace_id, employee_id);
"""


class SqliteHCMLeaveRepository:
    """Thread-safe SQLite storage for HCM leave entitlements and requests."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._mutation_active = False
        self._init_tables()

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Serialize the read/validate/write transition and commit its effects together."""
        self._conn.execute("BEGIN IMMEDIATE")
        self._mutation_active = True
        try:
            with self._conn:
                yield
        finally:
            self._mutation_active = False

    def close(self) -> None:
        self._conn.close()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def _init_tables(self) -> None:
        self._conn.executescript(CREATE_HCM_LEAVE_TABLES_SQL)
        self._conn.commit()

    def bind_employee(self, workspace_id: str, employee_id: str, user_id: str) -> None:
        """Persist an explicit manager-provisioned link to an existing identity.

        Existing links cannot be reassigned by updating an entitlement balance.
        Historical unbound employees remain unbound; ownership is never inferred
        from a previous caller-controlled leave request.
        """
        with nullcontext() if self._mutation_active else self._conn:
            user = self._conn.execute("SELECT id FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
            if user is None:
                raise HCMLeaveError("leave_employee_identity_missing", "An existing active user identity is required.")
            self._conn.execute(
                "INSERT INTO hcm_employee_identities(workspace_id,employee_id,user_id) VALUES(?,?,?) "
                "ON CONFLICT(workspace_id,employee_id) DO NOTHING", (workspace_id, employee_id, user_id),
            )
            if not self.employee_is_linked_to(workspace_id, employee_id, user_id):
                raise HCMLeaveError("leave_employee_identity_conflict", "The employee already has a different identity link.")

    def employee_is_linked_to(self, workspace_id: str, employee_id: str, user_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM hcm_employee_identities WHERE workspace_id=? AND employee_id=? AND user_id=?",
            (workspace_id, employee_id, user_id),
        ).fetchone() is not None

    def employee_identity_id(self, workspace_id: str, employee_id: str) -> str | None:
        """Return the explicitly provisioned stable owner, never a legacy label."""
        row = self._conn.execute(
            "SELECT user_id FROM hcm_employee_identities WHERE workspace_id=? AND employee_id=?",
            (workspace_id, employee_id),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def record_action(self, workspace_id: str, object_id: str, action: str, *, actor_user_id: str, actor_label: str) -> None:
        """Append redacted business evidence inside the caller-owned mutation."""
        if not self._mutation_active:
            raise HCMLeaveError("leave_transaction_required", "Leave audit requires the business transaction.")
        append_audit_event(
            self._conn, actor_user_id=actor_user_id, actor_label=actor_label, object_type="hcm.leave",
            object_id=object_id, action=action, metadata={"schema_version": 1, "workspace_id": workspace_id},
        )

    def get_balance(
        self, workspace_id: str, employee_id: str, leave_type: str
    ) -> LeaveEntitlementBalance | None:
        cursor = self._conn.execute(
            """
            SELECT employee_id, leave_type, annual_entitlement_days, accrued_days, consumed_days
            FROM hcm_leave_entitlement_balances
            WHERE workspace_id = ? AND employee_id = ? AND leave_type = ?
            """,
            (workspace_id, employee_id, leave_type),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LeaveEntitlementBalance(
            employee_id=row[0],
            leave_type=cast(LeaveCategory, row[1]),
            annual_entitlement_days=row[2],
            accrued_days=row[3],
            consumed_days=row[4],
        )

    def save_balance(self, workspace_id: str, balance: LeaveEntitlementBalance) -> None:
        with nullcontext() if self._mutation_active else self._conn:
            self._conn.execute(
                """
                INSERT INTO hcm_leave_entitlement_balances (
                    workspace_id, employee_id, leave_type,
                    annual_entitlement_days, accrued_days, consumed_days
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, employee_id, leave_type) DO UPDATE SET
                    annual_entitlement_days = excluded.annual_entitlement_days,
                    accrued_days = excluded.accrued_days,
                    consumed_days = excluded.consumed_days
                """,
                (
                    workspace_id,
                    balance.employee_id,
                    balance.leave_type,
                    balance.annual_entitlement_days,
                    balance.accrued_days,
                    balance.consumed_days,
                ),
            )

    def get_request(self, workspace_id: str, request_id: str) -> LeaveRequest | None:
        cursor = self._conn.execute(
            """
            SELECT request_id, employee_id, employee_user_id, leave_type,
                   start_date, end_date, requested_days, status, reason,
                   approved_by_user_id, rejection_reason
            FROM hcm_leave_requests
            WHERE workspace_id = ? AND request_id = ?
            """,
            (workspace_id, request_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LeaveRequest(
            request_id=row[0],
            employee_id=row[1],
            employee_user_id=row[2],
            leave_type=cast(LeaveCategory, row[3]),
            start_date=row[4],
            end_date=row[5],
            requested_days=row[6],
            status=cast(LeaveStatus, row[7]),
            reason=row[8],
            approved_by_user_id=row[9],
            rejection_reason=row[10],
        )

    def save_request(self, workspace_id: str, request: LeaveRequest, *, create_only: bool = False) -> None:
        with nullcontext() if self._mutation_active else self._conn:
            cursor = self._conn.execute(
                "".join(("""
                INSERT INTO hcm_leave_requests (
                    workspace_id, request_id, employee_id, employee_user_id,
                    leave_type, start_date, end_date, requested_days,
                    status, reason, approved_by_user_id, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, "ON CONFLICT(workspace_id, request_id) DO NOTHING" if create_only else """
                ON CONFLICT(workspace_id, request_id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    approved_by_user_id = excluded.approved_by_user_id,
                    rejection_reason = excluded.rejection_reason
                """)),
                (
                    workspace_id,
                    request.request_id,
                    request.employee_id,
                    request.employee_user_id,
                    request.leave_type,
                    request.start_date,
                    request.end_date,
                    request.requested_days,
                    request.status,
                    request.reason,
                    request.approved_by_user_id,
                    request.rejection_reason,
                ),
            )

            if create_only and cursor.rowcount != 1:
                raise HCMLeaveError("leave_request_exists", "A leave request with this identifier already exists.")

    def list_requests(
        self, workspace_id: str, employee_id: str | None = None
    ) -> list[LeaveRequest]:
        if employee_id is not None:
            cursor = self._conn.execute(
                """
                SELECT request_id, employee_id, employee_user_id, leave_type,
                       start_date, end_date, requested_days, status, reason,
                       approved_by_user_id, rejection_reason
                FROM hcm_leave_requests
                WHERE workspace_id = ? AND employee_id = ?
                ORDER BY start_date DESC
                """,
                (workspace_id, employee_id),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT request_id, employee_id, employee_user_id, leave_type,
                       start_date, end_date, requested_days, status, reason,
                       approved_by_user_id, rejection_reason
                FROM hcm_leave_requests
                WHERE workspace_id = ?
                ORDER BY start_date DESC
                """,
                (workspace_id,),
            )
        return [
            LeaveRequest(
                request_id=row[0],
                employee_id=row[1],
                employee_user_id=row[2],
                leave_type=cast(LeaveCategory, row[3]),
                start_date=row[4],
                end_date=row[5],
                requested_days=row[6],
                status=cast(LeaveStatus, row[7]),
                reason=row[8],
                approved_by_user_id=row[9],
                rejection_reason=row[10],
            )
            for row in cursor.fetchall()
        ]
