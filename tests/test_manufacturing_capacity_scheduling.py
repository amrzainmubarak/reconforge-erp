"""Tests for Work Center capacity scheduling, conflict detection, and atomic reallocation."""

import pytest

from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    book_capacity_slot,
    release_capacity_slot,
    reschedule_capacity_slot,
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

