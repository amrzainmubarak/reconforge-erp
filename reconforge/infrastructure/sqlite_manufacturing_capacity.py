"""SQLite persistence adapter for Work Center Calendars and Capacity Slot Reservations."""

from __future__ import annotations

import json
import sqlite3
import threading

from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    WorkCenterShift,
    book_capacity_slot,
)
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import PlatformError

SQLITE_CAPACITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS workcenter_calendars (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    name TEXT NOT NULL,
    daily_capacity_minutes INTEGER NOT NULL,
    blackout_dates TEXT NOT NULL,
    fixed_asset_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, workcenter_id)
);

CREATE TABLE IF NOT EXISTS workcenter_shifts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    name TEXT NOT NULL,
    start_minute INTEGER NOT NULL,
    end_minute INTEGER NOT NULL,
    break_minutes INTEGER NOT NULL,
    days_of_week TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, workcenter_id, shift_id)
);

CREATE TABLE IF NOT EXISTS capacity_slot_reservations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    workcenter_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    scheduled_date TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_minute INTEGER,
    end_minute INTEGER,
    shift_id TEXT,
    status TEXT NOT NULL DEFAULT 'BOOKED',
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, reservation_id)
);

CREATE INDEX IF NOT EXISTS idx_capacity_slots_lookup
ON capacity_slot_reservations (workspace_id, workcenter_id, scheduled_date, status);
"""


class SqliteManufacturingCapacityRepository:
    """Thread-safe SQLite storage for work center calendars and capacity slot bookings."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.executescript(SQLITE_CAPACITY_SCHEMA)

    def save_calendar(self, *, workspace_id: str, calendar: WorkCenterCalendar) -> None:
        now = utc_now_text()
        record_id = f"{workspace_id}:{calendar.workcenter_id}"
        blackouts_json = json.dumps(sorted(calendar.blackout_dates))

        with self._lock:
            try:
                with self._conn:
                    if not self._conn.in_transaction:
                        self._conn.execute("BEGIN IMMEDIATE")
                    self._conn.execute(
                        """
                        INSERT INTO workcenter_calendars (
                            id, workspace_id, workcenter_id, name,
                            daily_capacity_minutes, blackout_dates, fixed_asset_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (workspace_id, workcenter_id) DO UPDATE SET
                            name = excluded.name,
                            daily_capacity_minutes = excluded.daily_capacity_minutes,
                            blackout_dates = excluded.blackout_dates,
                            fixed_asset_id = excluded.fixed_asset_id,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record_id,
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
                    self._conn.execute(
                        "DELETE FROM workcenter_shifts WHERE workspace_id = ? AND workcenter_id = ?",
                        (workspace_id, calendar.workcenter_id),
                    )
                    for shift in calendar.shifts:
                        shift_rec_id = f"{workspace_id}:{calendar.workcenter_id}:{shift.shift_id}"
                        dow_json = json.dumps(sorted(shift.days_of_week))
                        self._conn.execute(
                            """
                            INSERT INTO workcenter_shifts (
                                id, workspace_id, workcenter_id, shift_id, name,
                                start_minute, end_minute, break_minutes, days_of_week, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                shift_rec_id,
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
            except sqlite3.Error as exc:
                raise PlatformError(f"Failed to save work center calendar: {exc}") from exc

    def get_calendar(self, *, workspace_id: str, workcenter_id: str) -> WorkCenterCalendar | None:
        cur = self._conn.execute(
            """
            SELECT workcenter_id, name, daily_capacity_minutes, blackout_dates, fixed_asset_id
            FROM workcenter_calendars
            WHERE workspace_id = ? AND workcenter_id = ?
            """,
            (workspace_id, workcenter_id),
        )
        row = cur.fetchone()
        if not row:
            return None

        wc_id, name, daily_cap, blackouts_raw, fixed_asset_id = row
        blackout_dates = frozenset(json.loads(blackouts_raw))

        shift_cur = self._conn.execute(
            """
            SELECT shift_id, name, start_minute, end_minute, break_minutes, days_of_week
            FROM workcenter_shifts
            WHERE workspace_id = ? AND workcenter_id = ?
            ORDER BY start_minute ASC
            """,
            (workspace_id, workcenter_id),
        )
        shifts: list[WorkCenterShift] = []
        for s_row in shift_cur.fetchall():
            s_id, s_name, s_start, s_end, s_break, s_dow_raw = s_row
            shifts.append(
                WorkCenterShift(
                    shift_id=s_id,
                    name=s_name,
                    start_minute=s_start,
                    end_minute=s_end,
                    break_minutes=s_break,
                    days_of_week=frozenset(json.loads(s_dow_raw)),
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

    def list_calendars(self, *, workspace_id: str) -> list[WorkCenterCalendar]:
        cur = self._conn.execute(
            "SELECT workcenter_id FROM workcenter_calendars WHERE workspace_id = ? ORDER BY workcenter_id ASC",
            (workspace_id,),
        )
        results: list[WorkCenterCalendar] = []
        for row in cur.fetchall():
            cal = self.get_calendar(workspace_id=workspace_id, workcenter_id=row[0])
            if cal:
                results.append(cal)
        return results

    def list_reservations(
        self,
        *,
        workspace_id: str,
        workcenter_id: str | None = None,
        scheduled_date: str | None = None,
        active_only: bool = True,
    ) -> list[CapacitySlotReservation]:
        conditions = ["workspace_id = ?"]
        params: list[object] = [workspace_id]
        if workcenter_id:
            conditions.append("workcenter_id = ?")
            params.append(workcenter_id)
        if scheduled_date:
            conditions.append("scheduled_date = ?")
            params.append(scheduled_date)
        if active_only:
            conditions.append("status = 'BOOKED'")

        query = f"""
            SELECT reservation_id, workcenter_id, work_order_id, operation_sequence,
                   scheduled_date, duration_minutes, start_minute, end_minute, shift_id
            FROM capacity_slot_reservations
            WHERE {' AND '.join(conditions)}
            ORDER BY scheduled_date ASC, start_minute ASC, reservation_id ASC
        """
        cur = self._conn.execute(query, tuple(params))
        slots: list[CapacitySlotReservation] = []
        for r in cur.fetchall():
            slots.append(
                CapacitySlotReservation(
                    reservation_id=r[0],
                    workcenter_id=r[1],
                    work_order_id=r[2],
                    operation_sequence=r[3],
                    scheduled_date=r[4],
                    duration_minutes=r[5],
                    start_minute=r[6],
                    end_minute=r[7],
                    shift_id=r[8],
                )
            )
        return slots

    def book_slot(
        self,
        *,
        workspace_id: str,
        slot: CapacitySlotReservation,
    ) -> CapacitySlotReservation:
        cal = self.get_calendar(workspace_id=workspace_id, workcenter_id=slot.workcenter_id)
        if not cal:
            raise CapacitySchedulingError(
                "calendar_not_found",
                f"Work center calendar '{slot.workcenter_id}' not found.",
            )

        with self._lock, self._conn:
            if not self._conn.in_transaction:
                self._conn.execute("BEGIN IMMEDIATE")

            active = self.list_reservations(
                workspace_id=workspace_id,
                workcenter_id=slot.workcenter_id,
                scheduled_date=slot.scheduled_date,
                active_only=True,
            )

            # Run domain validation and overbooking/overlap checks
            book_capacity_slot(active, slot, cal)

            rec_id = f"{workspace_id}:{slot.reservation_id}"
            now = utc_now_text()
            self._conn.execute(
                """
                INSERT INTO capacity_slot_reservations (
                    id, workspace_id, reservation_id, workcenter_id,
                    work_order_id, operation_sequence, scheduled_date,
                    duration_minutes, start_minute, end_minute, shift_id,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BOOKED', ?)
                """,
                (
                    rec_id,
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
        return slot

    def release_slot(
        self,
        *,
        workspace_id: str,
        work_order_id: str,
        operation_sequence: int,
    ) -> None:
        with self._lock, self._conn:
            if not self._conn.in_transaction:
                self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                """
                SELECT reservation_id FROM capacity_slot_reservations
                WHERE workspace_id = ? AND work_order_id = ? AND operation_sequence = ? AND status = 'BOOKED'
                """,
                (workspace_id, work_order_id, operation_sequence),
            )
            row = cur.fetchone()
            if not row:
                raise CapacitySchedulingError(
                    "capacity_not_found",
                    f"No active slot found for work order '{work_order_id}' sequence {operation_sequence}.",
                )

            self._conn.execute(
                """
                UPDATE capacity_slot_reservations
                SET status = 'RELEASED'
                WHERE workspace_id = ? AND work_order_id = ? AND operation_sequence = ? AND status = 'BOOKED'
                """,
                (workspace_id, work_order_id, operation_sequence),
            )

    def reschedule_slot(
        self,
        *,
        workspace_id: str,
        work_order_id: str,
        operation_sequence: int,
        new_slot: CapacitySlotReservation,
    ) -> CapacitySlotReservation:
        cal = self.get_calendar(workspace_id=workspace_id, workcenter_id=new_slot.workcenter_id)
        if not cal:
            raise CapacitySchedulingError(
                "calendar_not_found",
                f"Work center calendar '{new_slot.workcenter_id}' not found.",
            )

        with self._lock, self._conn:
            if not self._conn.in_transaction:
                self._conn.execute("BEGIN IMMEDIATE")

                active = self.list_reservations(
                    workspace_id=workspace_id,
                    workcenter_id=new_slot.workcenter_id,
                    scheduled_date=new_slot.scheduled_date,
                    active_only=True,
                )

                # Release existing slot logically from in-memory pool to validate domain
                filtered_active = [
                    s for s in active
                    if not (s.work_order_id == work_order_id and s.operation_sequence == operation_sequence)
                ]
                book_capacity_slot(filtered_active, new_slot, cal)

                rec_id = f"{workspace_id}:{new_slot.reservation_id}"
                now = utc_now_text()
                self._conn.execute(
                    """
                    UPDATE capacity_slot_reservations
                    SET status = 'RELEASED'
                    WHERE workspace_id = ? AND work_order_id = ? AND operation_sequence = ? AND status = 'BOOKED'
                    """,
                    (workspace_id, work_order_id, operation_sequence),
                )
                self._conn.execute(
                    """
                    INSERT INTO capacity_slot_reservations (
                        id, workspace_id, reservation_id, workcenter_id,
                        work_order_id, operation_sequence, scheduled_date,
                        duration_minutes, start_minute, end_minute, shift_id,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BOOKED', ?)
                    """,
                    (
                        rec_id,
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
        return new_slot
