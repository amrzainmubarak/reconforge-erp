"""Tests for Work Center Finite Capacity Planning, Calendars, SQLite/Postgres repos, and API routes."""

from __future__ import annotations

import sqlite3
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reconforge.api.errors import APIError, api_error_handler
from reconforge.api.routes.manufacturing_capacity import (
    router,
)
from reconforge.auth.models import LocalUser
from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    WorkCenterShift,
)
from reconforge.infrastructure.postgres_manufacturing_capacity import (
    PostgresManufacturingCapacityRepository,
)
from reconforge.infrastructure.sqlite_manufacturing_capacity import (
    SqliteManufacturingCapacityRepository,
)


@pytest.fixture
def test_user() -> LocalUser:
    return LocalUser(
        id="usr_planner_01",
        username="mfg_planner",
        display_name="Manufacturing Planner",
    )


def test_sqlite_capacity_repository_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SqliteManufacturingCapacityRepository(conn)

    shift1 = WorkCenterShift(
        shift_id="SHIFT-DAY",
        name="Day Shift",
        start_minute=480,   # 08:00
        end_minute=1020,   # 17:00
        break_minutes=60,  # 1 hr lunch -> 480 net min
        days_of_week=frozenset(range(5)),  # Mon-Fri
    )
    calendar = WorkCenterCalendar(
        workcenter_id="WC-MILL-01",
        name="CNC Vertical Mill 1",
        daily_capacity_minutes=480,
        blackout_dates=frozenset({"2026-12-25"}),
        shifts=(shift1,),
        fixed_asset_id="FA-MACH-001",
    )

    repo.save_calendar(workspace_id="ws_mfg", calendar=calendar)

    # Fetch calendar
    saved_cal = repo.get_calendar(workspace_id="ws_mfg", workcenter_id="WC-MILL-01")
    assert saved_cal is not None
    assert saved_cal.name == "CNC Vertical Mill 1"
    assert saved_cal.fixed_asset_id == "FA-MACH-001"
    assert len(saved_cal.shifts) == 1
    assert saved_cal.shifts[0].net_working_minutes == 480
    assert "2026-12-25" in saved_cal.blackout_dates

    # List calendars
    cals = repo.list_calendars(workspace_id="ws_mfg")
    assert len(cals) == 1
    assert cals[0].workcenter_id == "WC-MILL-01"

    # Book slot 1: Monday 2026-11-23 from 08:00 to 11:00 (180 min)
    slot1 = CapacitySlotReservation(
        reservation_id="RES-001",
        workcenter_id="WC-MILL-01",
        work_order_id="WO-001",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=180,
        start_minute=480,
        end_minute=660,
        shift_id="SHIFT-DAY",
    )
    booked1 = repo.book_slot(workspace_id="ws_mfg", slot=slot1)
    assert booked1.reservation_id == "RES-001"

    # Interval conflict check: same workcenter, same date, overlapping interval [540, 720]
    conflicting_slot = CapacitySlotReservation(
        reservation_id="RES-CONFLICT",
        workcenter_id="WC-MILL-01",
        work_order_id="WO-002",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=180,
        start_minute=540,
        end_minute=720,
        shift_id="SHIFT-DAY",
    )
    with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation"):
        repo.book_slot(workspace_id="ws_mfg", slot=conflicting_slot)

    # Blackout date refusal
    blackout_slot = CapacitySlotReservation(
        reservation_id="RES-BLACKOUT",
        workcenter_id="WC-MILL-01",
        work_order_id="WO-003",
        operation_sequence=1,
        scheduled_date="2026-12-25",
        duration_minutes=60,
    )
    with pytest.raises(CapacitySchedulingError, match="unavailable on 2026-12-25"):
        repo.book_slot(workspace_id="ws_mfg", slot=blackout_slot)

    # Book non-overlapping slot 2: 11:00 to 15:00 (240 min)
    # Total so far: 180 + 240 = 420 <= 480
    slot2 = CapacitySlotReservation(
        reservation_id="RES-002",
        workcenter_id="WC-MILL-01",
        work_order_id="WO-002",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=240,
        start_minute=660,
        end_minute=900,
        shift_id="SHIFT-DAY",
    )
    repo.book_slot(workspace_id="ws_mfg", slot=slot2)

    # Overbooking total daily capacity check: 420 + 120 = 540 > 480
    slot3 = CapacitySlotReservation(
        reservation_id="RES-003",
        workcenter_id="WC-MILL-01",
        work_order_id="WO-003",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=120,
    )
    with pytest.raises(CapacitySchedulingError, match="exceeds capacity"):
        repo.book_slot(workspace_id="ws_mfg", slot=slot3)

    # List active reservations
    active_slots = repo.list_reservations(workspace_id="ws_mfg", workcenter_id="WC-MILL-01")
    assert len(active_slots) == 2

    # Release slot 1
    repo.release_slot(workspace_id="ws_mfg", work_order_id="WO-001", operation_sequence=1)
    active_after_release = repo.list_reservations(workspace_id="ws_mfg", workcenter_id="WC-MILL-01")
    assert len(active_after_release) == 1
    assert active_after_release[0].reservation_id == "RES-002"

    # Reschedule slot 2 to Tuesday 2026-11-24
    new_slot2 = CapacitySlotReservation(
        reservation_id="RES-002-RESCHED",
        workcenter_id="WC-MILL-01",
        work_order_id="WO-002",
        operation_sequence=1,
        scheduled_date="2026-11-24",
        duration_minutes=240,
        start_minute=480,
        end_minute=720,
        shift_id="SHIFT-DAY",
    )
    rescheduled = repo.reschedule_slot(
        workspace_id="ws_mfg",
        work_order_id="WO-002",
        operation_sequence=1,
        new_slot=new_slot2,
    )
    assert rescheduled.reservation_id == "RES-002-RESCHED"
    assert rescheduled.scheduled_date == "2026-11-24"


def test_postgres_capacity_repository_scoping_and_rls() -> None:
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_cursor.fetchone.return_value = ("tenant_mfg_corp", "org-a", "ws-a", "entity-a", "entity-a")
    mock_conn.transaction.return_value.__enter__ = MagicMock(return_value=None)
    mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

    repo = PostgresManufacturingCapacityRepository(mock_conn, "tenant_mfg_corp")
    assert repo.tenant_id == "tenant_mfg_corp"

    # Verify RLS session setting
    repo._scope()
    # Joining an active repository must preserve all five authenticated GUCs.
    assert "current_setting('app.tenant_id'" in mock_conn.execute.call_args_list[0].args[0]
    assert not any("set_config(" in call.args[0] for call in mock_conn.execute.call_args_list)



def test_postgres_capacity_repository_book_slot_advisory_lock_and_row_lock() -> None:
    mock_conn = MagicMock()
    mock_conn.transaction.return_value.__enter__ = MagicMock(return_value=None)
    mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

    def execute_side_effect(query: str, params: Any = None) -> MagicMock:
        cursor = MagicMock()
        if "current_setting('app.tenant_id'" in query:
            cursor.fetchone.return_value = ("tenant_mfg_corp", "org-a", "ws-a", "entity-a", "entity-a")
        elif "FROM reconforge.workcenter_calendars" in query:
            cursor.fetchone.return_value = ("WC-PG-01", "Postgres CNC", 480, "[]", None)
        elif "FROM reconforge.workcenter_shifts" in query or (
            "FROM reconforge.capacity_slot_reservations" in query and "FOR UPDATE" in query
        ):
            cursor.fetchall.return_value = []
        elif "audit_ledger_state" in query:
            cursor.fetchone.return_value = {"last_sequence": 0, "last_event_hash": "0" * 64}
        else:
            cursor.fetchall.return_value = []
            cursor.fetchone.return_value = None
        return cursor

    mock_conn.execute.side_effect = execute_side_effect

    repo = PostgresManufacturingCapacityRepository(mock_conn, "tenant_mfg_corp")

    slot = CapacitySlotReservation(
        reservation_id="RES-PG-01",
        workcenter_id="WC-PG-01",
        work_order_id="WO-PG-01",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=120,
        start_minute=480,
        end_minute=600,
    )
    booked = repo.book_slot(workspace_id="ws_mfg", slot=slot)
    assert booked.reservation_id == "RES-PG-01"

    # Verify advisory lock was acquired
    advisory_calls = [
        call for call in mock_conn.execute.call_args_list
        if "pg_advisory_xact_lock" in str(call)
    ]
    assert len(advisory_calls) == 1
    expected_lock_key = "capacity_booking:tenant_mfg_corp:ws_mfg:WC-PG-01:2026-11-23"
    assert advisory_calls[0][0][1] == (expected_lock_key,)

    # Verify FOR UPDATE row lock was used in reservation query
    for_update_calls = [
        call for call in mock_conn.execute.call_args_list
        if "FROM reconforge.capacity_slot_reservations" in str(call[0][0]) and "FOR UPDATE" in str(call[0][0])
    ]
    assert len(for_update_calls) == 1


def test_postgres_capacity_repository_book_slot_conflict_propagates_directly() -> None:
    mock_conn = MagicMock()
    mock_conn.transaction.return_value.__enter__ = MagicMock(return_value=None)
    mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

    def execute_side_effect(query: str, params: Any = None) -> MagicMock:
        cursor = MagicMock()
        if "current_setting('app.tenant_id'" in query:
            cursor.fetchone.return_value = ("tenant_mfg_corp", "org-a", "ws-a", "entity-a", "entity-a")
        elif "FROM reconforge.workcenter_calendars" in query:
            cursor.fetchone.return_value = ("WC-PG-01", "Postgres CNC", 480, "[]", None)
        elif "FROM reconforge.workcenter_shifts" in query:
            cursor.fetchall.return_value = []
        elif "FROM reconforge.capacity_slot_reservations" in query and "FOR UPDATE" in query:
            cursor.fetchall.return_value = [
                ("RES-EXISTING", "WC-PG-01", "WO-OLD", 1, "2026-11-23", 120, 480, 600, None)
            ]
        else:
            cursor.fetchall.return_value = []
            cursor.fetchone.return_value = None
        return cursor

    mock_conn.execute.side_effect = execute_side_effect

    repo = PostgresManufacturingCapacityRepository(mock_conn, "tenant_mfg_corp")

    slot = CapacitySlotReservation(
        reservation_id="RES-PG-CONFLICT",
        workcenter_id="WC-PG-01",
        work_order_id="WO-PG-02",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=120,
        start_minute=480,
        end_minute=600,
    )
    with pytest.raises(CapacitySchedulingError) as exc_info:
        repo.book_slot(workspace_id="ws_mfg", slot=slot)
    assert exc_info.value.code == "capacity_conflict"


def test_postgres_capacity_repository_reschedule_slot_advisory_lock() -> None:
    mock_conn = MagicMock()
    mock_conn.transaction.return_value.__enter__ = MagicMock(return_value=None)
    mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

    def execute_side_effect(query: str, params: Any = None) -> MagicMock:
        cursor = MagicMock()
        if "current_setting('app.tenant_id'" in query:
            cursor.fetchone.return_value = ("tenant_mfg_corp", "org-a", "ws-a", "entity-a", "entity-a")
        elif "FROM reconforge.workcenter_calendars" in query:
            cursor.fetchone.return_value = ("WC-PG-01", "Postgres CNC", 480, "[]", None)
        elif "FROM reconforge.workcenter_shifts" in query:
            cursor.fetchall.return_value = []
        elif "FROM reconforge.capacity_slot_reservations" in query and "FOR UPDATE" in query:
            # Active slots contains the one being rescheduled
            cursor.fetchall.return_value = [
                ("RES-OLD", "WC-PG-01", "WO-PG-01", 1, "2026-11-23", 120, 480, 600, None)
            ]
        elif "audit_ledger_state" in query:
            cursor.fetchone.return_value = {"last_sequence": 0, "last_event_hash": "0" * 64}
        else:
            cursor.fetchall.return_value = []
            cursor.fetchone.return_value = None
        return cursor

    mock_conn.execute.side_effect = execute_side_effect

    repo = PostgresManufacturingCapacityRepository(mock_conn, "tenant_mfg_corp")

    new_slot = CapacitySlotReservation(
        reservation_id="RES-PG-NEW",
        workcenter_id="WC-PG-01",
        work_order_id="WO-PG-01",
        operation_sequence=1,
        scheduled_date="2026-11-23",
        duration_minutes=120,
        start_minute=600,
        end_minute=720,
    )
    rescheduled = repo.reschedule_slot(
        workspace_id="ws_mfg",
        work_order_id="WO-PG-01",
        operation_sequence=1,
        new_slot=new_slot,
    )
    assert rescheduled.reservation_id == "RES-PG-NEW"

    # Verify advisory lock was acquired with expected key
    advisory_calls = [
        call for call in mock_conn.execute.call_args_list
        if "pg_advisory_xact_lock" in str(call)
    ]
    assert len(advisory_calls) == 1
    expected_lock_key = "capacity_booking:tenant_mfg_corp:ws_mfg:WC-PG-01:2026-11-23"
    assert advisory_calls[0][0][1] == (expected_lock_key,)


def test_capacity_api_routes(tmp_path: Any, test_user: LocalUser) -> None:
    from reconforge.api.routes.manufacturing_capacity import (
        require_capacity_manage,
        require_capacity_read,
    )
    db_file = tmp_path / "test_capacity.db"

    app = FastAPI()
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.include_router(router, prefix="/api/v1")
    app.state.db_path = str(db_file)
    app.state.server_mode = False

    app.dependency_overrides[require_capacity_read] = lambda: test_user
    app.dependency_overrides[require_capacity_manage] = lambda: test_user

    client = TestClient(app)

    # 1. Create Calendar
    cal_data = {
        "workcenter_id": "WC-LATH-01",
        "name": "Precision Lathe",
        "daily_capacity_minutes": 480,
        "blackout_dates": ["2026-12-25"],
        "shifts": [
            {
                "shift_id": "SHIFT-1",
                "name": "Morning Shift",
                "start_minute": 480,
                "end_minute": 960,
                "break_minutes": 0,
                "days_of_week": [0, 1, 2, 3, 4],
            }
        ],
        "fixed_asset_id": "FA-LATH-09",
    }
    resp = client.post("/api/v1/manufacturing/capacity/calendars", json=cal_data)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "saved"

    # 2. Get Calendar
    resp_get = client.get("/api/v1/manufacturing/capacity/calendars/WC-LATH-01")
    assert resp_get.status_code == 200
    assert resp_get.json()["fixed_asset_id"] == "FA-LATH-09"

    # 3. Book Slot
    slot_payload = {
        "reservation_id": "RES-API-01",
        "workcenter_id": "WC-LATH-01",
        "work_order_id": "WO-LATH-100",
        "operation_sequence": 1,
        "scheduled_date": "2026-11-23",
        "duration_minutes": 120,
        "start_minute": 480,
        "end_minute": 600,
        "shift_id": "SHIFT-1",
    }
    resp_book = client.post("/api/v1/manufacturing/capacity/reservations", json=slot_payload)
    assert resp_book.status_code == 200
    assert resp_book.json()["status"] == "booked"

    # 4. Overlap refusal via API
    overlap_payload = {
        "reservation_id": "RES-API-02",
        "workcenter_id": "WC-LATH-01",
        "work_order_id": "WO-LATH-200",
        "operation_sequence": 1,
        "scheduled_date": "2026-11-23",
        "duration_minutes": 60,
        "start_minute": 540,
        "end_minute": 600,
        "shift_id": "SHIFT-1",
    }
    resp_overlap = client.post("/api/v1/manufacturing/capacity/reservations", json=overlap_payload)
    assert resp_overlap.status_code == 422
    assert "capacity_conflict" in resp_overlap.json()["error"]["code"]

    # 5. Reschedule via API
    resched_payload = {
        "work_order_id": "WO-LATH-100",
        "operation_sequence": 1,
        "new_slot": {
            "reservation_id": "RES-API-01-V2",
            "workcenter_id": "WC-LATH-01",
            "work_order_id": "WO-LATH-100",
            "operation_sequence": 1,
            "scheduled_date": "2026-11-24",
            "duration_minutes": 120,
            "start_minute": 480,
            "end_minute": 600,
            "shift_id": "SHIFT-1",
        },
    }
    resp_resched = client.post("/api/v1/manufacturing/capacity/reservations/reschedule", json=resched_payload)
    assert resp_resched.status_code == 200
    assert resp_resched.json()["status"] == "rescheduled"

    # 6. Release reservation via API
    resp_del = client.delete("/api/v1/manufacturing/capacity/reservations/WO-LATH-100/1")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "released"


def test_capacity_api_server_mode_fail_closed() -> None:
    from reconforge.api.routes.manufacturing_capacity import require_capacity_read

    app = FastAPI()
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.include_router(router, prefix="/api/v1")
    app.state.server_mode = True  # Enterprise mode requires postgres factory

    user = LocalUser(id="u1", username="admin", display_name="Admin")
    app.dependency_overrides[require_capacity_read] = lambda: user

    client = TestClient(app)
    resp = client.get("/api/v1/manufacturing/capacity/calendars")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "server_postgres_unavailable"
