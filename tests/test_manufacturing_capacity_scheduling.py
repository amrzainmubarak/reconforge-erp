import concurrent.futures
import sqlite3
from pathlib import Path

import pytest

from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    WorkCenterShift,
    book_capacity_slot,
    release_capacity_slot,
    reschedule_capacity_slot,
)
from reconforge.infrastructure.sqlite_manufacturing_capacity import (
    SqliteManufacturingCapacityRepository,
)


@pytest.fixture
def cnc_calendar() -> WorkCenterCalendar:
    return WorkCenterCalendar(
        workcenter_id="WC-CNC-01",
        name="5-Axis CNC Milling Center",
        daily_capacity_minutes=480,  # 8-hour shift
        blackout_dates=frozenset({"2026-11-26", "2026-12-25"}),
    )


def test_capacity_booking_within_limits(cnc_calendar: WorkCenterCalendar) -> None:
    slot1 = CapacitySlotReservation(
        reservation_id="RES-001",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=240,
    )
    booked = book_capacity_slot([], slot1, cnc_calendar)
    assert len(booked) == 1
    assert booked[0].duration_minutes == 240

    # Book second operation on same day (240 + 200 = 440 <= 480)
    slot2 = CapacitySlotReservation(
        reservation_id="RES-002",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1002",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=200,
    )
    booked2 = book_capacity_slot(booked, slot2, cnc_calendar)
    assert len(booked2) == 2


def test_capacity_overbooking_refusal(cnc_calendar: WorkCenterCalendar) -> None:
    slot1 = CapacitySlotReservation(
        reservation_id="RES-001",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=300,
    )
    booked = book_capacity_slot([], slot1, cnc_calendar)

    # 300 + 200 = 500 > 480: must be rejected
    slot2 = CapacitySlotReservation(
        reservation_id="RES-002",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1002",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=200,
    )
    with pytest.raises(CapacitySchedulingError, match="exceeds capacity"):
        book_capacity_slot(booked, slot2, cnc_calendar)


def test_blackout_maintenance_date_refusal(cnc_calendar: WorkCenterCalendar) -> None:
    slot = CapacitySlotReservation(
        reservation_id="RES-003",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1003",
        operation_sequence=1,
        scheduled_date="2026-12-25",  # Blackout holiday
        duration_minutes=60,
    )
    with pytest.raises(CapacitySchedulingError, match="unavailable on 2026-12-25"):
        book_capacity_slot([], slot, cnc_calendar)


def test_duplicate_operation_booking_refusal(cnc_calendar: WorkCenterCalendar) -> None:
    slot1 = CapacitySlotReservation(
        reservation_id="RES-001",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
    )
    booked = book_capacity_slot([], slot1, cnc_calendar)

    # Attempt to book same WO and sequence again
    slot1_dup = CapacitySlotReservation(
        reservation_id="RES-001-B",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-21",
        duration_minutes=120,
    )
    with pytest.raises(CapacitySchedulingError, match="already has a booked slot"):
        book_capacity_slot(booked, slot1_dup, cnc_calendar)


def test_atomic_rescheduling(cnc_calendar: WorkCenterCalendar) -> None:
    slot1 = CapacitySlotReservation(
        reservation_id="RES-001",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=480,  # Fills entire day
    )
    booked = book_capacity_slot([], slot1, cnc_calendar)

    # Reschedule to another day
    new_slot1 = CapacitySlotReservation(
        reservation_id="RES-001-RE",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-21",
        duration_minutes=480,
    )
    rescheduled = reschedule_capacity_slot(booked, "WO-1001", 1, new_slot1, cnc_calendar)
    assert len(rescheduled) == 1
    assert rescheduled[0].scheduled_date == "2026-11-21"

    # Now original date 2026-11-20 is free again for booking
    slot2 = CapacitySlotReservation(
        reservation_id="RES-002",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1002",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=480,
    )
    booked_after = book_capacity_slot(rescheduled, slot2, cnc_calendar)
    assert len(booked_after) == 2


def test_release_capacity_slot(cnc_calendar: WorkCenterCalendar) -> None:
    slot1 = CapacitySlotReservation(
        reservation_id="RES-001",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-1001",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=240,
    )
    booked = book_capacity_slot([], slot1, cnc_calendar)
    assert len(booked) == 1
    released = release_capacity_slot(booked, "WO-1001", 1)
    assert len(released) == 0

    with pytest.raises(CapacitySchedulingError, match="No active slot found"):
        release_capacity_slot(released, "WO-1001", 1)


def test_shift_calendar_definition_and_capacity_derivation() -> None:
    morning = WorkCenterShift(
        shift_id="SHIFT-MORN",
        name="Morning Shift",
        start_minute=480,  # 08:00
        end_minute=960,   # 16:00 (480m)
        break_minutes=60,  # net 420m
        days_of_week=frozenset({0, 1, 2, 3, 4}),  # Mon-Fri
    )
    assert morning.net_working_minutes == 420

    cal = WorkCenterCalendar(
        workcenter_id="WC-PAINT-01",
        name="Automated Paint Booth",
        shifts=(morning,),
    )
    assert cal.daily_capacity_minutes == 420


def test_shift_validation_errors() -> None:
    with pytest.raises(CapacitySchedulingError, match="Shift window must satisfy"):
        WorkCenterShift("S1", "Invalid Window", start_minute=900, end_minute=800)

    with pytest.raises(CapacitySchedulingError, match="Break minutes"):
        WorkCenterShift("S2", "Invalid Break", start_minute=480, end_minute=600, break_minutes=150)

    with pytest.raises(CapacitySchedulingError, match="Day of week"):
        WorkCenterShift("S3", "Invalid Day", start_minute=480, end_minute=600, days_of_week=frozenset({7}))


def test_interval_reservation_validation_errors() -> None:
    # Missing end_minute when start_minute provided
    with pytest.raises(CapacitySchedulingError, match="Both start_minute and end_minute"):
        CapacitySlotReservation(
            reservation_id="R-ERR-1",
            workcenter_id="WC-CNC-01",
            work_order_id="WO-101",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=60,
            start_minute=480,
            end_minute=None,
        )

    # Duration mismatch: end - start = 120, but duration = 60
    with pytest.raises(CapacitySchedulingError, match="Slot duration .* must equal end_minute - start_minute"):
        CapacitySlotReservation(
            reservation_id="R-ERR-2",
            workcenter_id="WC-CNC-01",
            work_order_id="WO-101",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=60,
            start_minute=480,
            end_minute=600,
        )


def test_interval_overlap_conflict_rejection() -> None:
    cal = WorkCenterCalendar(
        workcenter_id="WC-CNC-01",
        name="CNC",
        daily_capacity_minutes=960,
    )

    # Book slot 1: 08:00 to 10:00 (minutes 480 to 600)
    slot1 = CapacitySlotReservation(
        reservation_id="RES-01",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-101",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=480,
        end_minute=600,
    )
    booked = book_capacity_slot([], slot1, cal)
    assert len(booked) == 1

    # Overlapping slot 2: 09:30 to 11:30 (minutes 570 to 690) -> partial overlap
    slot2_conflict = CapacitySlotReservation(
        reservation_id="RES-02",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-102",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=570,
        end_minute=690,
    )
    with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-01'"):
        book_capacity_slot(booked, slot2_conflict, cal)

    # Enclosed slot 3: 08:30 to 09:30 (minutes 510 to 570) -> inside slot1
    slot3_enclosed = CapacitySlotReservation(
        reservation_id="RES-03",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-103",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=60,
        start_minute=510,
        end_minute=570,
    )
    with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-01'"):
        book_capacity_slot(booked, slot3_enclosed, cal)

    # Non-overlapping adjacent slot 4: 10:00 to 12:00 (minutes 600 to 720) -> books cleanly!
    slot4_adjacent = CapacitySlotReservation(
        reservation_id="RES-04",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-104",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=600,
        end_minute=720,
    )
    booked2 = book_capacity_slot(booked, slot4_adjacent, cal)
    assert len(booked2) == 2


def test_shift_boundary_enforcement() -> None:
    # Shift is Monday through Friday, 08:00 (480) to 16:00 (960)
    shift = WorkCenterShift(
        shift_id="DAY-SHIFT",
        name="Day Shift",
        start_minute=480,
        end_minute=960,
        break_minutes=0,
        days_of_week=frozenset({0, 1, 2, 3, 4}),  # Mon-Fri
    )
    cal = WorkCenterCalendar(
        workcenter_id="WC-WELD-01",
        name="Robotic Welding Cell",
        daily_capacity_minutes=480,
        shifts=(shift,),
    )

    # 2026-11-20 is a Friday (weekday = 4)
    # Valid slot within shift
    slot_ok = CapacitySlotReservation(
        reservation_id="RES-W1",
        workcenter_id="WC-WELD-01",
        work_order_id="WO-201",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=480,
        end_minute=600,
        shift_id="DAY-SHIFT",
    )
    booked = book_capacity_slot([], slot_ok, cal)
    assert len(booked) == 1

    # Slot outside shift hours (e.g. starting at 07:00 = 420)
    slot_outside = CapacitySlotReservation(
        reservation_id="RES-W2",
        workcenter_id="WC-WELD-01",
        work_order_id="WO-202",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=420,
        end_minute=540,
    )
    with pytest.raises(CapacitySchedulingError, match="does not fall within operating hours"):
        book_capacity_slot(booked, slot_outside, cal)

    # 2026-11-21 is Saturday (weekday = 5) -> no active shift
    slot_saturday = CapacitySlotReservation(
        reservation_id="RES-W3",
        workcenter_id="WC-WELD-01",
        work_order_id="WO-203",
        operation_sequence=1,
        scheduled_date="2026-11-21",
        duration_minutes=120,
        start_minute=480,
        end_minute=600,
    )
    with pytest.raises(CapacitySchedulingError, match="no active shifts"):
        book_capacity_slot([], slot_saturday, cal)


def test_atomic_interval_rescheduling_within_same_day() -> None:
    cal = WorkCenterCalendar(
        workcenter_id="WC-CNC-01",
        name="CNC",
        daily_capacity_minutes=960,
    )

    # Book WO-101 at [480, 600) and WO-102 at [600, 720)
    slot1 = CapacitySlotReservation(
        reservation_id="R1",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-101",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=480,
        end_minute=600,
    )
    slot2 = CapacitySlotReservation(
        reservation_id="R2",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-102",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=600,
        end_minute=720,
    )
    booked = book_capacity_slot([], slot1, cal)
    booked = book_capacity_slot(booked, slot2, cal)
    assert len(booked) == 2

    # Attempt to reschedule WO-101 to [660, 780) -> conflicts with WO-102 [600, 720)!
    conflicting_new_slot = CapacitySlotReservation(
        reservation_id="R1-MOVE-ERR",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-101",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=660,
        end_minute=780,
    )
    with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'R2'"):
        reschedule_capacity_slot(booked, "WO-101", 1, conflicting_new_slot, cal)

    # Reschedule WO-101 to a clear slot [720, 840) -> succeeds!
    valid_new_slot = CapacitySlotReservation(
        reservation_id="R1-MOVED",
        workcenter_id="WC-CNC-01",
        work_order_id="WO-101",
        operation_sequence=1,
        scheduled_date="2026-11-20",
        duration_minutes=120,
        start_minute=720,
        end_minute=840,
    )
    rescheduled = reschedule_capacity_slot(booked, "WO-101", 1, valid_new_slot, cal)
    assert len(rescheduled) == 2
    r1_after = next(s for s in rescheduled if s.work_order_id == "WO-101")
    assert r1_after.start_minute == 720
    assert r1_after.end_minute == 840


def test_sqlite_capacity_slot_booking_concurrency_serializes_and_rejects_overlap(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent_mfg_capacity.db"
    init_conn = sqlite3.connect(str(db_path))
    init_repo = SqliteManufacturingCapacityRepository(init_conn)
    cal = WorkCenterCalendar(
        workcenter_id="WC-CONC-01",
        name="Concurrent Test Machine",
        daily_capacity_minutes=480,
        shifts=(),
    )
    init_repo.save_calendar(workspace_id="ws_01", calendar=cal)
    init_conn.close()

    results: list[tuple[int, str]] = []

    def worker(idx: int) -> None:
        c = sqlite3.connect(str(db_path), timeout=10.0)
        repo = SqliteManufacturingCapacityRepository(c)
        slot = CapacitySlotReservation(
            reservation_id=f"RES-CONC-{idx}",
            workcenter_id="WC-CONC-01",
            work_order_id=f"WO-CONC-{idx}",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        try:
            repo.book_slot(workspace_id="ws_01", slot=slot)
            results.append((idx, "success"))
        except CapacitySchedulingError as e:
            results.append((idx, e.code))
        finally:
            c.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(worker, i) for i in range(5)]
        for f in futures:
            f.result()

    successes = [r for r in results if r[1] == "success"]
    conflicts = [r for r in results if r[1] == "capacity_conflict"]
    assert len(successes) == 1
    assert len(conflicts) == 4

    verify_conn = sqlite3.connect(str(db_path))
    verify_repo = SqliteManufacturingCapacityRepository(verify_conn)
    booked = verify_repo.list_reservations(workspace_id="ws_01", workcenter_id="WC-CONC-01")
    verify_conn.close()
    assert len(booked) == 1
    assert booked[0].start_minute == 480
    assert booked[0].end_minute == 600


def test_sqlite_capacity_slot_concurrent_adjacent_slots_succeed(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent_adjacent.db"
    init_conn = sqlite3.connect(str(db_path))
    init_repo = SqliteManufacturingCapacityRepository(init_conn)
    cal = WorkCenterCalendar(
        workcenter_id="WC-ADJ-01",
        name="Adjacent Test Machine",
        daily_capacity_minutes=480,
        shifts=(),
    )
    init_repo.save_calendar(workspace_id="ws_01", calendar=cal)
    init_conn.close()

    def worker(idx: int, start: int, end: int) -> str:
        c = sqlite3.connect(str(db_path), timeout=10.0)
        repo = SqliteManufacturingCapacityRepository(c)
        slot = CapacitySlotReservation(
            reservation_id=f"RES-ADJ-{idx}",
            workcenter_id="WC-ADJ-01",
            work_order_id=f"WO-ADJ-{idx}",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=end - start,
            start_minute=start,
            end_minute=end,
        )
        try:
            repo.book_slot(workspace_id="ws_01", slot=slot)
            return "success"
        finally:
            c.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, 1, 480, 600)
        f2 = pool.submit(worker, 2, 600, 720)
        res1 = f1.result()
        res2 = f2.result()

    assert res1 == "success"
    assert res2 == "success"

    verify_conn = sqlite3.connect(str(db_path))
    verify_repo = SqliteManufacturingCapacityRepository(verify_conn)
    booked = verify_repo.list_reservations(workspace_id="ws_01", workcenter_id="WC-ADJ-01")
    verify_conn.close()
    assert len(booked) == 2

