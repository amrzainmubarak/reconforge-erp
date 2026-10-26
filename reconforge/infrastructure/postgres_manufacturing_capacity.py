"""PostgreSQL enterprise persistence with FORCE RLS for Work Center Calendars and Capacity Slot Reservations."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    WorkCenterShift,
    book_capacity_slot,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope as set_local_tenant_scope
from reconforge.platform.common import PlatformError

POSTGRES_CAPACITY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.workcenter_calendars (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    name TEXT NOT NULL,
    daily_capacity_minutes INTEGER NOT NULL,
    blackout_dates JSONB NOT NULL DEFAULT '[]',
    fixed_asset_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, workcenter_id)
);
ALTER TABLE reconforge.workcenter_calendars ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.workcenter_calendars FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.workcenter_calendars;
CREATE POLICY tenant_scope ON reconforge.workcenter_calendars
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.workcenter_shifts (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    name TEXT NOT NULL,
    start_minute INTEGER NOT NULL,
    end_minute INTEGER NOT NULL,
    break_minutes INTEGER NOT NULL,
    days_of_week JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, workcenter_id, shift_id)
);
ALTER TABLE reconforge.workcenter_shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.workcenter_shifts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.workcenter_shifts;
CREATE POLICY tenant_scope ON reconforge.workcenter_shifts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.capacity_slot_reservations (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    scheduled_date DATE NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_minute INTEGER,
    end_minute INTEGER,
    shift_id TEXT,
    status TEXT NOT NULL DEFAULT 'BOOKED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, reservation_id)
);
ALTER TABLE reconforge.capacity_slot_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.capacity_slot_reservations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.capacity_slot_reservations;
CREATE POLICY tenant_scope ON reconforge.capacity_slot_reservations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresManufacturingCapacityRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for work center calendars and capacity slot bookings."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def save_calendar(
        self,
        *,
        workspace_id: str,
        calendar: WorkCenterCalendar,
        created_by: str = "system",
    ) -> None:
        blackouts_json = json.dumps(sorted(calendar.blackout_dates))
        now = utc_now_text()
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.workcenter_calendars (
                        tenant_id, workspace_id, workcenter_id, name,
                        daily_capacity_minutes, blackout_dates, fixed_asset_id,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, workcenter_id) DO UPDATE SET
                        name = excluded.name,
                        daily_capacity_minutes = excluded.daily_capacity_minutes,
                        blackout_dates = excluded.blackout_dates,
                        fixed_asset_id = excluded.fixed_asset_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        workspace_id,
                        calendar.workcenter_id,
                        calendar.name,
                        calendar.daily_capacity_minutes,
                        blackouts_json,
                        calendar.fixed_asset_id,
                        now,
                        now,
                    ),
                )
                self.connection.execute(
                    """
                    DELETE FROM reconforge.workcenter_shifts
                    WHERE tenant_id = %s AND workspace_id = %s AND workcenter_id = %s
                    """,
                    (self.tenant_id, workspace_id, calendar.workcenter_id),
                )
                for shift in calendar.shifts:
                    dow_json = json.dumps(sorted(shift.days_of_week))
                    self.connection.execute(
                        """
                        INSERT INTO reconforge.workcenter_shifts (
                            tenant_id, workspace_id, workcenter_id, shift_id, name,
                            start_minute, end_minute, break_minutes, days_of_week, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s)
                        """,
                        (
                            self.tenant_id,
                            workspace_id,
                            calendar.workcenter_id,
                            shift.shift_id,
                            shift.name,
                            shift.start_minute,
                            shift.end_minute,
                            shift.break_minutes,
                            dow_json,
                            now,
                        ),
                    )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=created_by,
                    actor_user_id=created_by,
                    object_type="workcenter_calendar",
                    object_id=calendar.workcenter_id,
                    action="calendar_saved",
                    after_hash=f"{calendar.workcenter_id}:{calendar.daily_capacity_minutes}",
                    metadata={
                        "workspace_id": workspace_id,
                        "shifts_count": len(calendar.shifts),
                        "fixed_asset_id": calendar.fixed_asset_id,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL work center calendar save failed: {exc}") from exc

    def get_calendar(self, *, workspace_id: str, workcenter_id: str) -> WorkCenterCalendar | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workcenter_id, name, daily_capacity_minutes, blackout_dates, fixed_asset_id
                    FROM reconforge.workcenter_calendars
                    WHERE tenant_id = %s AND workspace_id = %s AND workcenter_id = %s
                    """,
                    (self.tenant_id, workspace_id, workcenter_id),
                )
                row = cur.fetchone()
                if not row:
                    return None

                wc_id, name, daily_cap, blackouts_raw, fixed_asset_id = row
                try:
                    blackouts = json.loads(blackouts_raw) if isinstance(blackouts_raw, str) else blackouts_raw
                except (ValueError, RecursionError):
                    raise CapacitySchedulingError(
                        "capacity_persisted_data_invalid", "Persisted blackout restrictions are invalid.",
                    ) from None
                if not isinstance(blackouts, (list, tuple)) or any(type(value) is not str for value in blackouts):
                    raise CapacitySchedulingError(
                        "capacity_persisted_data_invalid", "Persisted blackout restrictions require an array of dates.",
                    )
                try:
                    if any(date.fromisoformat(value).isoformat() != value for value in blackouts):
                        raise ValueError
                except ValueError:
                    raise CapacitySchedulingError(
                        "capacity_persisted_data_invalid", "Persisted blackout dates require canonical YYYY-MM-DD values.",
                    ) from None
                blackout_dates = frozenset(blackouts)

                shift_cur = self.connection.execute(
                    """
                    SELECT shift_id, name, start_minute, end_minute, break_minutes, days_of_week
                    FROM reconforge.workcenter_shifts
                    WHERE tenant_id = %s AND workspace_id = %s AND workcenter_id = %s
                    ORDER BY start_minute ASC
                    """,
                    (self.tenant_id, workspace_id, workcenter_id),
                )
                shifts: list[WorkCenterShift] = []
                for s_row in shift_cur.fetchall():
                    s_id, s_name, s_start, s_end, s_break, s_dow_raw = s_row
                    try:
                        weekdays = json.loads(s_dow_raw) if isinstance(s_dow_raw, str) else s_dow_raw
                    except (ValueError, RecursionError):
                        raise CapacitySchedulingError(
                            "capacity_persisted_data_invalid", "Persisted weekday restrictions are invalid.",
                        ) from None
                    if not isinstance(weekdays, (list, tuple)) or any(
                        type(value) is not int or not 0 <= value <= 6 for value in weekdays
                    ):
                        raise CapacitySchedulingError(
                            "capacity_persisted_data_invalid", "Persisted weekday restrictions require integers from zero to six.",
                        )
                    dow_set = frozenset(weekdays)
                    shifts.append(
                        WorkCenterShift(
                            shift_id=s_id,
                            name=s_name,
                            start_minute=s_start,
                            end_minute=s_end,
                            break_minutes=s_break,
                            days_of_week=dow_set,
                        )
                    )

                return WorkCenterCalendar(
                    workcenter_id=wc_id,
                    name=name,
                    daily_capacity_minutes=daily_cap,
                    blackout_dates=blackout_dates,
                    shifts=tuple(shifts),
                    fixed_asset_id=fixed_asset_id,
                )
        except CapacitySchedulingError:
            raise
        except Exception as exc:
            raise PlatformError(f"PostgreSQL work center calendar get failed: {exc}") from exc

    def list_calendars(self, *, workspace_id: str) -> list[WorkCenterCalendar]:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workcenter_id FROM reconforge.workcenter_calendars
                    WHERE tenant_id = %s AND workspace_id = %s
                    ORDER BY workcenter_id ASC
                    """,
                    (self.tenant_id, workspace_id),
                )
                rows = cur.fetchall()
            results: list[WorkCenterCalendar] = []
            for r in rows:
                cal = self.get_calendar(workspace_id=workspace_id, workcenter_id=r[0])
                if cal:
                    results.append(cal)
            return results
        except Exception as exc:
            raise PlatformError(f"PostgreSQL work center calendar list failed: {exc}") from exc

    def list_reservations(
        self,
        *,
        workspace_id: str,
        workcenter_id: str | None = None,
        scheduled_date: str | None = None,
        active_only: bool = True,
        for_update: bool = False,
    ) -> list[CapacitySlotReservation]:
        try:
            with self.connection.transaction():
                self._scope()
                conditions = ["tenant_id = %s", "workspace_id = %s"]
                params: list[Any] = [self.tenant_id, workspace_id]
                if workcenter_id:
                    conditions.append("workcenter_id = %s")
                    params.append(workcenter_id)
                if scheduled_date:
                    conditions.append("scheduled_date = %s")
                    params.append(scheduled_date)
                if active_only:
                    conditions.append("status = 'BOOKED'")

                lock_clause = " FOR UPDATE" if for_update else ""
                query = "".join(("""
                    SELECT reservation_id, workcenter_id, work_order_id, operation_sequence,
                           scheduled_date, duration_minutes, start_minute, end_minute, shift_id
                    FROM reconforge.capacity_slot_reservations
                    WHERE """, (' AND '.join(conditions)), """
                    ORDER BY scheduled_date ASC, start_minute ASC, reservation_id ASC""", (lock_clause), """
                """))
                cur = self.connection.execute(query, tuple(params))
                slots: list[CapacitySlotReservation] = []
                for r in cur.fetchall():
                    slots.append(
                        CapacitySlotReservation(
                            reservation_id=r[0],
                            workcenter_id=r[1],
                            work_order_id=r[2],
                            operation_sequence=r[3],
                            scheduled_date=str(r[4]),
                            duration_minutes=r[5],
                            start_minute=r[6],
                            end_minute=r[7],
                            shift_id=r[8],
                        )
                    )
                return slots
        except Exception as exc:
            raise PlatformError(f"PostgreSQL list capacity reservations failed: {exc}") from exc

    def book_slot(
        self,
        *,
        workspace_id: str,
        slot: CapacitySlotReservation,
        created_by: str = "system",
    ) -> CapacitySlotReservation:
        cal = self.get_calendar(workspace_id=workspace_id, workcenter_id=slot.workcenter_id)
        if not cal:
            raise CapacitySchedulingError(
                "calendar_not_found",
                f"Work center calendar '{slot.workcenter_id}' not found.",
            )

        lock_key = f"capacity_booking:{self.tenant_id}:{workspace_id}:{slot.workcenter_id}:{slot.scheduled_date}"
        now = utc_now_text()
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_key,),
                )
                active = self.list_reservations(
                    workspace_id=workspace_id,
                    workcenter_id=slot.workcenter_id,
                    scheduled_date=slot.scheduled_date,
                    active_only=True,
                    for_update=True,
                )
                book_capacity_slot(active, slot, cal)

                self.connection.execute(
                    """
                    INSERT INTO reconforge.capacity_slot_reservations (
                        tenant_id, workspace_id, reservation_id, workcenter_id,
                        work_order_id, operation_sequence, scheduled_date,
                        duration_minutes, start_minute, end_minute, shift_id,
                        status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'BOOKED', %s)
                    """,
                    (
                        self.tenant_id,
                        workspace_id,
                        slot.reservation_id,
                        slot.workcenter_id,
                        slot.work_order_id,
                        slot.operation_sequence,
                        slot.scheduled_date,
                        slot.duration_minutes,
                        slot.start_minute,
                        slot.end_minute,
                        slot.shift_id,
                        now,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=created_by,
                    actor_user_id=created_by,
                    object_type="capacity_slot",
                    object_id=slot.reservation_id,
                    action="slot_booked",
                    after_hash=f"{slot.workcenter_id}:{slot.scheduled_date}:{slot.duration_minutes}",
                    metadata={
                        "workspace_id": workspace_id,
                        "work_order_id": slot.work_order_id,
                        "operation_sequence": slot.operation_sequence,
                    },
                )
        except CapacitySchedulingError:
            raise
        except Exception as exc:
            raise PlatformError(f"PostgreSQL capacity slot book failed: {exc}") from exc

        return slot

    def release_slot(
        self,
        *,
        workspace_id: str,
        work_order_id: str,
        operation_sequence: int,
        actor: str = "system",
    ) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT reservation_id FROM reconforge.capacity_slot_reservations
                    WHERE tenant_id = %s AND workspace_id = %s AND work_order_id = %s
                          AND operation_sequence = %s AND status = 'BOOKED'
                    FOR UPDATE
                    """,
                    (self.tenant_id, workspace_id, work_order_id, operation_sequence),
                )
                row = cur.fetchone()
                if not row:
                    raise CapacitySchedulingError(
                        "capacity_not_found",
                        f"No active slot found for work order '{work_order_id}' sequence {operation_sequence}.",
                    )
                reservation_id = row[0]
                self.connection.execute(
                    """
                    UPDATE reconforge.capacity_slot_reservations
                    SET status = 'RELEASED'
                    WHERE tenant_id = %s AND workspace_id = %s AND work_order_id = %s
                          AND operation_sequence = %s AND status = 'BOOKED'
                    """,
                    (self.tenant_id, workspace_id, work_order_id, operation_sequence),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="capacity_slot",
                    object_id=reservation_id,
                    action="slot_released",
                    after_hash="RELEASED",
                    metadata={
                        "workspace_id": workspace_id,
                        "work_order_id": work_order_id,
                        "operation_sequence": operation_sequence,
                    },
                )
        except CapacitySchedulingError:
            raise
        except Exception as exc:
            raise PlatformError(f"PostgreSQL capacity slot release failed: {exc}") from exc

    def reschedule_slot(
        self,
        *,
        workspace_id: str,
        work_order_id: str,
        operation_sequence: int,
        new_slot: CapacitySlotReservation,
        actor: str = "system",
    ) -> CapacitySlotReservation:
        cal = self.get_calendar(workspace_id=workspace_id, workcenter_id=new_slot.workcenter_id)
        if not cal:
            raise CapacitySchedulingError(
                "calendar_not_found",
                f"Work center calendar '{new_slot.workcenter_id}' not found.",
            )

        lock_key = f"capacity_booking:{self.tenant_id}:{workspace_id}:{new_slot.workcenter_id}:{new_slot.scheduled_date}"
        now = utc_now_text()
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_key,),
                )
                active = self.list_reservations(
                    workspace_id=workspace_id,
                    workcenter_id=new_slot.workcenter_id,
                    scheduled_date=new_slot.scheduled_date,
                    active_only=True,
                    for_update=True,
                )

                filtered_active = [
                    s for s in active
                    if not (s.work_order_id == work_order_id and s.operation_sequence == operation_sequence)
                ]
                book_capacity_slot(filtered_active, new_slot, cal)

                self.connection.execute(
                    """
                    UPDATE reconforge.capacity_slot_reservations
                    SET status = 'RELEASED'
                    WHERE tenant_id = %s AND workspace_id = %s AND work_order_id = %s
                          AND operation_sequence = %s AND status = 'BOOKED'
                    """,
                    (self.tenant_id, workspace_id, work_order_id, operation_sequence),
                )
                self.connection.execute(
                    """
                    INSERT INTO reconforge.capacity_slot_reservations (
                        tenant_id, workspace_id, reservation_id, workcenter_id,
                        work_order_id, operation_sequence, scheduled_date,
                        duration_minutes, start_minute, end_minute, shift_id,
                        status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'BOOKED', %s)
                    """,
                    (
                        self.tenant_id,
                        workspace_id,
                        new_slot.reservation_id,
                        new_slot.workcenter_id,
                        new_slot.work_order_id,
                        new_slot.operation_sequence,
                        new_slot.scheduled_date,
                        new_slot.duration_minutes,
                        new_slot.start_minute,
                        new_slot.end_minute,
                        new_slot.shift_id,
                        now,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="capacity_slot",
                    object_id=new_slot.reservation_id,
                    action="slot_rescheduled",
                    after_hash=f"{new_slot.workcenter_id}:{new_slot.scheduled_date}:{new_slot.duration_minutes}",
                    metadata={
                        "workspace_id": workspace_id,
                        "old_work_order_id": work_order_id,
                        "old_sequence": operation_sequence,
                    },
                )
        except CapacitySchedulingError:
            raise
        except Exception as exc:
            raise PlatformError(f"PostgreSQL capacity slot reschedule failed: {exc}") from exc

        return new_slot
