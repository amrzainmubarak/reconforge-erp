"""PostgreSQL tenant/workspace-scoped persistence for HCM Leave Entitlements and Requests with FORCE RLS."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveCategory,
    LeaveEntitlementBalance,
    LeaveRequest,
    LeaveStatus,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id

POSTGRES_HCM_LEAVE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.hcm_leave_entitlement_balances (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    annual_entitlement_days INTEGER NOT NULL,
    accrued_days INTEGER NOT NULL,
    consumed_days INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, employee_id, leave_type)
);
ALTER TABLE reconforge.hcm_leave_entitlement_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.hcm_leave_entitlement_balances FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_entitlement_balances;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_entitlement_balances
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.hcm_leave_requests (
    tenant_id TEXT NOT NULL,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, request_id)
);
ALTER TABLE reconforge.hcm_leave_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.hcm_leave_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_requests;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_requests
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE INDEX IF NOT EXISTS idx_pg_hcm_leave_requests_employee
ON reconforge.hcm_leave_requests (tenant_id, workspace_id, employee_id);
"""


class PostgresHCMLeaveRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for HCM leave entitlements and requests."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self._mutation_active = False

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Hold request and entitlement row locks until the complete transition commits."""
        with self.connection.transaction():
            self._scope()
            self._mutation_active = True
            try:
                yield
            finally:
                self._mutation_active = False

    def close(self) -> None:
        self.connection.close()

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def get_balance(
        self, workspace_id: str, employee_id: str, leave_type: str
    ) -> LeaveEntitlementBalance | None:
        self._scope()
        cursor = self.connection.execute(
            "".join(("""
            SELECT employee_id, leave_type, annual_entitlement_days, accrued_days, consumed_days
            FROM reconforge.hcm_leave_entitlement_balances
            WHERE workspace_id = %s AND employee_id = %s AND leave_type = %s
            """, " FOR UPDATE" if self._mutation_active else "")),
            (workspace_id, employee_id, leave_type),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LeaveEntitlementBalance(
            employee_id=row[0],
            leave_type=cast(LeaveCategory, row[1]),
            annual_entitlement_days=int(row[2]),
            accrued_days=int(row[3]),
            consumed_days=int(row[4]),
        )

    def save_balance(self, workspace_id: str, balance: LeaveEntitlementBalance) -> None:
        with self.connection.transaction():
            self._scope()
            self.connection.execute(
                """
                INSERT INTO reconforge.hcm_leave_entitlement_balances (
                    tenant_id, workspace_id, employee_id, leave_type,
                    annual_entitlement_days, accrued_days, consumed_days
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, employee_id, leave_type) DO UPDATE SET
                    annual_entitlement_days = excluded.annual_entitlement_days,
                    accrued_days = excluded.accrued_days,
                    consumed_days = excluded.consumed_days
                """,
                (
                    self.tenant_id,
                    workspace_id,
                    balance.employee_id,
                    balance.leave_type,
                    balance.annual_entitlement_days,
                    balance.accrued_days,
                    balance.consumed_days,
                ),
            )

    def get_request(self, workspace_id: str, request_id: str) -> LeaveRequest | None:
        self._scope()
        cursor = self.connection.execute(
            "".join(("""
            SELECT request_id, employee_id, employee_user_id, leave_type,
                   start_date, end_date, requested_days, status, reason,
                   approved_by_user_id, rejection_reason
            FROM reconforge.hcm_leave_requests
            WHERE workspace_id = %s AND request_id = %s
            """, " FOR UPDATE" if self._mutation_active else "")),
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
            requested_days=int(row[6]),
            status=cast(LeaveStatus, row[7]),
            reason=row[8],
            approved_by_user_id=row[9],
            rejection_reason=row[10],
        )

    def save_request(self, workspace_id: str, request: LeaveRequest, *, create_only: bool = False) -> None:
        with self.connection.transaction():
            self._scope()
            cursor = self.connection.execute(
                "".join(("""
                INSERT INTO reconforge.hcm_leave_requests (
                    tenant_id, workspace_id, request_id, employee_id, employee_user_id,
                    leave_type, start_date, end_date, requested_days,
                    status, reason, approved_by_user_id, rejection_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, "ON CONFLICT(tenant_id, workspace_id, request_id) DO NOTHING" if create_only else """
                ON CONFLICT (tenant_id, workspace_id, request_id) DO UPDATE SET
                    status = excluded.status,
                    approved_by_user_id = excluded.approved_by_user_id,
                    rejection_reason = excluded.rejection_reason
                """)),
                (
                    self.tenant_id,
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
        self._scope()
        if employee_id:
            cursor = self.connection.execute(
                """
                SELECT request_id, employee_id, employee_user_id, leave_type,
                       start_date, end_date, requested_days, status, reason,
                       approved_by_user_id, rejection_reason
                FROM reconforge.hcm_leave_requests
                WHERE workspace_id = %s AND employee_id = %s
                ORDER BY start_date DESC
                """,
                (workspace_id, employee_id),
            )
        else:
            cursor = self.connection.execute(
                """
                SELECT request_id, employee_id, employee_user_id, leave_type,
                       start_date, end_date, requested_days, status, reason,
                       approved_by_user_id, rejection_reason
                FROM reconforge.hcm_leave_requests
                WHERE workspace_id = %s
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
                requested_days=int(row[6]),
                status=cast(LeaveStatus, row[7]),
                reason=row[8],
                approved_by_user_id=row[9],
                rejection_reason=row[10],
            )
            for row in cursor.fetchall()
        ]
