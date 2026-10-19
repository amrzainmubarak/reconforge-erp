"""Comprehensive tests for Equipment Maintenance integration, fixed asset linking, and calendar blackout booking."""

from __future__ import annotations

import pytest

from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    WorkCenterShift,
)
from reconforge.domain.manufacturing_maintenance import (
    MaintenanceError,
    MaintenanceSparePart,
    MaintenanceWorkOrder,
)


@pytest.fixture
def mill_calendar() -> WorkCenterCalendar:
    shift = WorkCenterShift(
        shift_id="SHIFT-01",
        name="Day Shift",
        start_minute=480,   # 08:00
        end_minute=1020,   # 17:00
        break_minutes=60,
    )
    return WorkCenterCalendar(
        workcenter_id="WC-MILL-05",
        name="Heavy Milling Center 5",
        daily_capacity_minutes=480,
        shifts=(shift,),
        fixed_asset_id="FA-EQUIP-1005",
    )


def test_maintenance_spare_part_costs() -> None:
    part1 = MaintenanceSparePart(
        item_id="PART-BEARING-01",
        part_name="High-Speed Spindle Bearing",
        quantity_required=2,
        unit_cost_minor=15_000,  # $150.00
    )
    assert part1.total_cost_minor == 30_000  # $300.00

    part2 = MaintenanceSparePart(
        item_id="PART-LUBRICANT-01",
        part_name="Synthetic Gear Oil (Liters)",
        quantity_required=5,
        unit_cost_minor=2_500,  # $25.00
    )
    assert part2.total_cost_minor == 12_500  # $125.00


def test_maintenance_order_validation(mill_calendar: WorkCenterCalendar) -> None:
    # Valid order
    mwo = MaintenanceWorkOrder(
        maintenance_order_id="MWO-2026-001",
        workcenter_id="WC-MILL-05",
        fixed_asset_id="FA-EQUIP-1005",
        maintenance_type="preventive",
        description="Quarterly Spindle Alignment & Oil Flush",
        scheduled_date="2026-11-25",
        start_minute=480,  # 08:00
        end_minute=720,    # 12:00
        labor_technician_id="TECH-MIKE",
        labor_rate_hourly_minor=75_000,  # $75.00/hr
    )
    assert mwo.duration_minutes == 240
    assert mwo.status == "draft"

    from reconforge.domain.finance_posting import FinancePostingError

    # Invalid window: end <= start
    with pytest.raises(FinancePostingError):
        MaintenanceWorkOrder(
            maintenance_order_id="MWO-ERR-1",
            workcenter_id="WC-MILL-05",
            fixed_asset_id="FA-EQUIP-1005",
            maintenance_type="preventive",
            description="Bad Window",
            scheduled_date="2026-11-25",
            start_minute=600,
            end_minute=500,
        )

    # Workcenter mismatch refusal
    with pytest.raises(MaintenanceError, match="does not match calendar"):
        mwo_mismatch = MaintenanceWorkOrder(
            maintenance_order_id="MWO-ERR-2",
            workcenter_id="WC-OTHER-99",
            fixed_asset_id="FA-EQUIP-1005",
            maintenance_type="preventive",
            description="Mismatch",
            scheduled_date="2026-11-25",
            start_minute=480,
            end_minute=600,
        )
        mwo_mismatch.schedule_and_book_blackout(calendar=mill_calendar)

    # Fixed asset mismatch refusal
    with pytest.raises(MaintenanceError, match="does not match maintenance asset"):
        mwo_asset_mismatch = MaintenanceWorkOrder(
            maintenance_order_id="MWO-ERR-3",
            workcenter_id="WC-MILL-05",
            fixed_asset_id="FA-WRONG-ASSET",
            maintenance_type="preventive",
            description="Wrong Asset",
            scheduled_date="2026-11-25",
            start_minute=480,
            end_minute=600,
        )
        mwo_asset_mismatch.schedule_and_book_blackout(calendar=mill_calendar)


def test_maintenance_auto_booking_slot_reservation(mill_calendar: WorkCenterCalendar) -> None:
    part = MaintenanceSparePart(
        item_id="PART-SEAL-01",
        part_name="Rotary Shaft Seal",
        quantity_required=1,
        unit_cost_minor=5_000,
    )
    mwo = MaintenanceWorkOrder(
        maintenance_order_id="MWO-2026-002",
        workcenter_id="WC-MILL-05",
        fixed_asset_id="FA-EQUIP-1005",
        maintenance_type="preventive",
        description="Hydraulic Seal Replacement",
        scheduled_date="2026-11-25",
        start_minute=480,  # 08:00
        end_minute=660,    # 11:00 (180 min)
        spare_parts=(part,),
        labor_technician_id="TECH-MIKE",
        labor_rate_hourly_minor=60_000,  # $60.00/hr
    )

    existing_prod_job = CapacitySlotReservation(
        reservation_id="RES-PROD-01",
        workcenter_id="WC-MILL-05",
        work_order_id="WO-PROD-101",
        operation_sequence=1,
        scheduled_date="2026-11-25",
        duration_minutes=180,
        start_minute=720,  # 12:00 to 15:00 (non-overlapping)
        end_minute=900,
    )

    scheduled_order, updated_cal, reservation = mwo.schedule_and_book_blackout(
        calendar=mill_calendar,
        existing_reservations=[existing_prod_job],
    )
    assert scheduled_order.status == "scheduled"
    assert reservation is not None
    assert reservation.reservation_id == "RES-MAINT-MWO-2026-002"
    assert reservation.duration_minutes == 180

    # Conflict check: existing job overlaps with maintenance window [480, 660]
    overlapping_job = CapacitySlotReservation(
        reservation_id="RES-PROD-OVERLAP",
        workcenter_id="WC-MILL-05",
        work_order_id="WO-PROD-102",
        operation_sequence=1,
        scheduled_date="2026-11-25",
        duration_minutes=120,
        start_minute=600,  # 10:00 to 12:00 -> conflicts with [480, 660]
        end_minute=720,
    )
    with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation"):
        mwo.schedule_and_book_blackout(
            calendar=mill_calendar,
            existing_reservations=[overlapping_job],
        )


def test_maintenance_full_day_blackout_calendar_update(mill_calendar: WorkCenterCalendar) -> None:
    mwo = MaintenanceWorkOrder(
        maintenance_order_id="MWO-ANNUAL-01",
        workcenter_id="WC-MILL-05",
        fixed_asset_id="FA-EQUIP-1005",
        maintenance_type="preventive",
        description="Annual Overhaul",
        scheduled_date="2026-12-01",
        start_minute=0,
        end_minute=1440,
    )
    scheduled_order, updated_cal, reservation = mwo.schedule_and_book_blackout(
        calendar=mill_calendar,
        as_full_day_blackout=True,
    )
    assert scheduled_order.status == "scheduled"
    assert "2026-12-01" in updated_cal.blackout_dates
    assert reservation is None


def test_maintenance_execution_and_cost_accumulation(mill_calendar: WorkCenterCalendar) -> None:
    part1 = MaintenanceSparePart("SP-BELT", "Drive Belt", 2, 10_000)      # 20_000 minor ($200.00)
    part2 = MaintenanceSparePart("SP-FILTER", "Air Filter", 1, 5_000)      # 5_000 minor ($50.00)

    mwo = MaintenanceWorkOrder(
        maintenance_order_id="MWO-EXEC-01",
        workcenter_id="WC-MILL-05",
        fixed_asset_id="FA-EQUIP-1005",
        maintenance_type="corrective",
        description="Emergency Belt Tension Repair",
        scheduled_date="2026-11-25",
        start_minute=480,
        end_minute=600,
        spare_parts=(part1, part2),
        labor_technician_id="TECH-SARAH",
        labor_rate_hourly_minor=80_000,  # $80.00/hr
    )

    scheduled, _, _ = mwo.schedule_and_book_blackout(calendar=mill_calendar)
    in_prog = scheduled.start_maintenance()
    assert in_prog.status == "in_progress"

    # Actual repair took 90 minutes (1.5 hrs)
    # Labor cost: (90 * 80_000 + 30) // 60 = 7_200_030 // 60 = 120_000 minor ($120.00)
    # Spare parts cost: 20_000 + 5_000 = 25_000 minor ($250.00)
    # Total cost: 120_000 + 25_000 = 145_000 minor ($1,450.00)
    completed = in_prog.complete_maintenance(
        actual_labor_minutes=90,
        notes="Replaced both belts and tightened tensioner to 45Nm.",
    )
    assert completed.status == "completed"
    assert completed.spare_parts_cost_minor == 25_000
    assert completed.labor_cost_minor == 120_000
    assert completed.total_maintenance_cost_minor == 145_000
    assert completed.completed_at is not None
