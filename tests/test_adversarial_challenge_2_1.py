"""Empirical adversarial challenge and stress-test harness for ReconForge ERP (Challenge Set 2.1).

Scope of Empirical Challenge:
1. Finite Capacity Scheduling Stress:
   - Exact boundary touches (adjacent right/left, contiguous chains)
   - Micro-overlaps (1-minute overlap on boundaries and subsets)
   - Midnight wrap-arounds, 24h limits, and invalid minute bounds
   - Multi-shift boundaries, inter-shift maintenance gaps, blackout dates
   - Capacity API routes and concurrent slot booking simulations
2. Segregation of Duties (SoD) Re-Verification:
   - Remediated VULN-SOD-01 and VULN-SOD-02 whitespace testing
   - Exhaustive whitespace combinations: standard, control, and unicode separators
   - Empirical proof of VULN-SOD-03: Unicode zero-width bypass of SoD
3. HCM Leave & Entitlement Edge Cases:
   - Leap-year (366 days) vs common-year (365 days) day proration against Fraction oracle
   - Negative balance creation and overdrawn leave prevention
   - Retroactive cancellations (boundary dates, already started, double cancel)
   - Annual rollover carryover caps, zero cap, and forfeiture arithmetic
4. CRM Subscription Proration Math:
   - Rational Fraction oracle comparison with half-up rounding over thousands of cases
   - Mid-month plan changes (upgrades, downgrades, same-tier, free tier)
   - Leap-year February vs common February vs full year proration
   - Cancellation refunds and boundary validations
"""

from __future__ import annotations

import concurrent.futures
import random
import sqlite3
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reconforge.api.errors import APIError, api_error_handler
from reconforge.api.routes.manufacturing_capacity import (
    require_capacity_manage,
    require_capacity_read,
)
from reconforge.api.routes.manufacturing_capacity import (
    router as mfg_capacity_router,
)
from reconforge.auth.models import LocalUser
from reconforge.domain.crm_contracts import (
    CustomerContract,
    CustomerQuotation,
    QuotationLineItem,
    Subscription,
    SubscriptionPlan,
    calculate_plan_change_proration,
    cancel_subscription_with_refund,
    terminate_contract,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveEntitlementBalance,
    LeaveRequest,
    accrue_prorated_entitlement,
    approve_leave_request,
    cancel_leave_request,
    reject_leave_request,
    rollover_leave_entitlement,
    submit_leave_request,
)
from reconforge.domain.manufacturing_capacity_scheduling import (
    MAX_MINUTES_PER_DAY,
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    WorkCenterShift,
    book_capacity_slot,
)
from reconforge.infrastructure.sqlite_manufacturing_capacity import (
    SqliteManufacturingCapacityRepository,
)

# ============================================================================
# ORACLES & MATHEMATICAL REFERENCE IMPLEMENTATIONS
# ============================================================================

def fraction_day_proration_oracle(amount_minor: int, total_period_days: int, active_days: int) -> int:
    """Exact rational Fraction oracle with standard half-up rounding."""
    if total_period_days <= 0 or not (0 <= active_days <= total_period_days):
        raise ValueError("Invalid proration arguments")
    if active_days == 0:
        return 0
    if active_days == total_period_days:
        return amount_minor
    frac = Fraction(amount_minor * active_days, total_period_days)
    # Half-up rounding on rational fraction: floor(frac + 1/2)
    return (frac.numerator * 2 + frac.denominator) // (frac.denominator * 2)


# ============================================================================
# CHALLENGE 1: WORK CENTER FINITE CAPACITY SCHEDULING STRESS
# ============================================================================

class TestWorkCenterFiniteCapacityStress:
    """Stress testing capacity scheduling: boundary touches, 1m overlaps, multi-shift, and API."""

    @pytest.fixture
    def shift_calendar_8h(self) -> WorkCenterCalendar:
        """Standard 8-hour shift calendar (08:00 to 16:00, 480 minutes)."""
        shift = WorkCenterShift(
            shift_id="SHIFT-08-16",
            name="Day Shift",
            start_minute=480,  # 08:00
            end_minute=960,   # 16:00
            break_minutes=0,
            days_of_week=frozenset({0, 1, 2, 3, 4}),  # Mon-Fri
        )
        return WorkCenterCalendar(
            workcenter_id="WC-STRESS-01",
            name="Stress Test Milling Cell",
            daily_capacity_minutes=480,
            blackout_dates=frozenset({"2026-12-25"}),
            shifts=(shift,),
        )

    @pytest.fixture
    def multi_shift_calendar(self) -> WorkCenterCalendar:
        """Dual-shift calendar with inter-shift maintenance gap:
        - Shift 1: 08:00 - 12:00 (480 - 720, 240m)
        - Maintenance / Lunch Gap: 12:00 - 13:00 (720 - 780, 60m)
        - Shift 2: 13:00 - 17:00 (780 - 1020, 240m)
        Total daily capacity = 480m.
        """
        shift1 = WorkCenterShift(
            shift_id="SHIFT-MORNING",
            name="Morning Shift",
            start_minute=480,
            end_minute=720,
            break_minutes=0,
            days_of_week=frozenset({0, 1, 2, 3, 4}),
        )
        shift2 = WorkCenterShift(
            shift_id="SHIFT-AFTERNOON",
            name="Afternoon Shift",
            start_minute=780,
            end_minute=1020,
            break_minutes=0,
            days_of_week=frozenset({0, 1, 2, 3, 4}),
        )
        return WorkCenterCalendar(
            workcenter_id="WC-MULTI-02",
            name="Dual Shift Cell with Maintenance Gap",
            daily_capacity_minutes=480,
            blackout_dates=frozenset({"2026-12-25"}),
            shifts=(shift1, shift2),
        )

    @pytest.fixture
    def continuous_24h_calendar(self) -> WorkCenterCalendar:
        """Continuous 24-hour production calendar without shift bounds."""
        return WorkCenterCalendar(
            workcenter_id="WC-24H-01",
            name="Continuous Smelting Pot",
            daily_capacity_minutes=MAX_MINUTES_PER_DAY,
            blackout_dates=frozenset({"2026-01-01"}),
            shifts=(),
        )

    # ------------------------------------------------------------------------
    # 1.1 Exact Boundary Touches
    # ------------------------------------------------------------------------

    def test_exact_boundary_touches_adjacent_right_and_left(
        self, shift_calendar_8h: WorkCenterCalendar
    ) -> None:
        """Adjacent slots touching at the exact boundary minute must NOT conflict."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-23",  # Monday
            duration_minutes=120,
            start_minute=600,  # 10:00
            end_minute=720,    # 12:00
            shift_id="SHIFT-08-16",
        )
        booked = book_capacity_slot([], base_slot, shift_calendar_8h)
        assert len(booked) == 1

        # Slot touching on the right boundary: [720, 840)
        touch_right = CapacitySlotReservation(
            reservation_id="RES-TOUCH-RIGHT",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=720,  # Exactly touches end of base_slot
            end_minute=840,
            shift_id="SHIFT-08-16",
        )
        booked = book_capacity_slot(booked, touch_right, shift_calendar_8h)
        assert len(booked) == 2

        # Slot touching on the left boundary: [480, 600)
        touch_left = CapacitySlotReservation(
            reservation_id="RES-TOUCH-LEFT",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-003",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,  # Exactly touches start of base_slot
            shift_id="SHIFT-08-16",
        )
        booked = book_capacity_slot(booked, touch_left, shift_calendar_8h)
        assert len(booked) == 3

        # All 3 contiguous slots are preserved in chronological order
        assert [s.reservation_id for s in booked] == ["RES-TOUCH-LEFT", "RES-BASE", "RES-TOUCH-RIGHT"]

    def test_continuous_adjacent_slot_chain(self, shift_calendar_8h: WorkCenterCalendar) -> None:
        """Chain of 8 adjacent 60-minute slots perfectly packing the 480-minute shift."""
        booked: list[CapacitySlotReservation] = []
        for i in range(8):
            start = 480 + (i * 60)
            end = start + 60
            slot = CapacitySlotReservation(
                reservation_id=f"RES-CHAIN-{i}",
                workcenter_id="WC-STRESS-01",
                work_order_id=f"WO-C-{i}",
                operation_sequence=1,
                scheduled_date="2026-11-23",
                duration_minutes=60,
                start_minute=start,
                end_minute=end,
                shift_id="SHIFT-08-16",
            )
            booked = book_capacity_slot(booked, slot, shift_calendar_8h)

        assert len(booked) == 8
        assert sum(s.duration_minutes for s in booked) == 480

        # Attempting to book even a 1-minute slot now must fail with capacity_conflict
        over_slot = CapacitySlotReservation(
            reservation_id="RES-OVER",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-OVER",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=1,
            start_minute=480,
            end_minute=481,
            shift_id="SHIFT-08-16",
        )
        with pytest.raises(CapacitySchedulingError) as exc_info:
            book_capacity_slot(booked, over_slot, shift_calendar_8h)
        assert exc_info.value.code == "capacity_conflict"

    # ------------------------------------------------------------------------
    # 1.2 Micro-Overlaps (1-Minute Boundary Incursions)
    # ------------------------------------------------------------------------

    def test_micro_overlap_one_minute_right_and_left(
        self, shift_calendar_8h: WorkCenterCalendar
    ) -> None:
        """A 1-minute overlap across boundaries must be strictly rejected."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=600,
            end_minute=720,
            shift_id="SHIFT-08-16",
        )
        booked = book_capacity_slot([], base_slot, shift_calendar_8h)

        # 1-minute right overlap: starts at 719 instead of 720
        right_incursion = CapacitySlotReservation(
            reservation_id="RES-INC-RIGHT",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-INC-R",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=60,
            start_minute=719,
            end_minute=779,
            shift_id="SHIFT-08-16",
        )
        with pytest.raises(CapacitySchedulingError) as exc_r:
            book_capacity_slot(booked, right_incursion, shift_calendar_8h)
        assert exc_r.value.code == "capacity_conflict"
        assert "RES-BASE" in str(exc_r.value)

        # 1-minute left overlap: ends at 601 instead of 600
        left_incursion = CapacitySlotReservation(
            reservation_id="RES-INC-LEFT",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-INC-L",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=60,
            start_minute=541,
            end_minute=601,
            shift_id="SHIFT-08-16",
        )
        with pytest.raises(CapacitySchedulingError) as exc_l:
            book_capacity_slot(booked, left_incursion, shift_calendar_8h)
        assert exc_l.value.code == "capacity_conflict"
        assert "RES-BASE" in str(exc_l.value)

    def test_micro_overlap_one_minute_contained_subsets(
        self, shift_calendar_8h: WorkCenterCalendar
    ) -> None:
        """1-minute incursion entirely inside the existing reservation [600, 720)."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-STRESS-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=600,
            end_minute=720,
            shift_id="SHIFT-08-16",
        )
        booked = book_capacity_slot([], base_slot, shift_calendar_8h)

        for start, end in [(600, 601), (659, 660), (719, 720), (601, 719)]:
            sub = CapacitySlotReservation(
                reservation_id=f"RES-SUB-{start}",
                workcenter_id="WC-STRESS-01",
                work_order_id=f"WO-SUB-{start}",
                operation_sequence=1,
                scheduled_date="2026-11-23",
                duration_minutes=end - start,
                start_minute=start,
                end_minute=end,
                shift_id="SHIFT-08-16",
            )
            with pytest.raises(CapacitySchedulingError) as exc_sub:
                book_capacity_slot(booked, sub, shift_calendar_8h)
            assert exc_sub.value.code == "capacity_conflict"

    # ------------------------------------------------------------------------
    # 1.3 Midnight Wrap-Arounds and 24-Hour Limits
    # ------------------------------------------------------------------------

    def test_full_day_continuous_24h_consumption(
        self, continuous_24h_calendar: WorkCenterCalendar
    ) -> None:
        """A full 24-hour reservation [0, 1440) consumes all capacity."""
        full_day = CapacitySlotReservation(
            reservation_id="RES-ALL-DAY",
            workcenter_id="WC-24H-01",
            work_order_id="WO-ALL-DAY",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=MAX_MINUTES_PER_DAY,
            start_minute=0,
            end_minute=MAX_MINUTES_PER_DAY,
        )
        booked = book_capacity_slot([], full_day, continuous_24h_calendar)
        assert len(booked) == 1

        # Attempt to book another slot on same date
        extra = CapacitySlotReservation(
            reservation_id="RES-EXTRA",
            workcenter_id="WC-24H-01",
            work_order_id="WO-EXTRA",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=1,
            start_minute=0,
            end_minute=1,
        )
        with pytest.raises(CapacitySchedulingError) as exc_info:
            book_capacity_slot(booked, extra, continuous_24h_calendar)
        assert exc_info.value.code == "capacity_conflict"

    def test_midnight_wrap_around_and_invalid_bounds(
        self, continuous_24h_calendar: WorkCenterCalendar
    ) -> None:
        """Attempts to wrap past midnight or pass out-of-bound minutes are rejected."""
        # 1. Wrap-around attempt: start 1400, end 60
        with pytest.raises(CapacitySchedulingError) as exc_wrap:
            CapacitySlotReservation(
                reservation_id="RES-WRAP",
                workcenter_id="WC-24H-01",
                work_order_id="WO-WRAP",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=100,
                start_minute=1400,
                end_minute=60,
            )
        assert exc_wrap.value.code == "capacity_interval_invalid"

        # 2. Negative start minute
        with pytest.raises(CapacitySchedulingError) as exc_neg:
            CapacitySlotReservation(
                reservation_id="RES-NEG",
                workcenter_id="WC-24H-01",
                work_order_id="WO-NEG",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=60,
                start_minute=-1,
                end_minute=59,
            )
        assert exc_neg.value.code == "capacity_interval_invalid"

        # 3. End minute exceeding 1440
        with pytest.raises(CapacitySchedulingError) as exc_beyond:
            CapacitySlotReservation(
                reservation_id="RES-BEYOND",
                workcenter_id="WC-24H-01",
                work_order_id="WO-BEYOND",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=60,
                start_minute=1381,
                end_minute=1441,
            )
        assert exc_beyond.value.code == "capacity_interval_invalid"

        # 4. Duration mismatch
        with pytest.raises(CapacitySchedulingError) as exc_dur:
            CapacitySlotReservation(
                reservation_id="RES-MISMATCH",
                workcenter_id="WC-24H-01",
                work_order_id="WO-MISMATCH",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=60,
                start_minute=100,
                end_minute=200,  # 100m interval, but duration=60
            )
        assert exc_dur.value.code == "capacity_duration_mismatch"

    # ------------------------------------------------------------------------
    # 1.4 Multi-Shift Boundaries & Inter-Shift Maintenance Gaps
    # ------------------------------------------------------------------------

    def test_multi_shift_operating_windows_and_gaps(
        self, multi_shift_calendar: WorkCenterCalendar
    ) -> None:
        """Verifies multi-shift boundary enforcement, gap refusal, and cross-shift rejection."""
        # 1. Valid booking inside Morning Shift [480, 720]
        slot_morning = CapacitySlotReservation(
            reservation_id="RES-MORN",
            workcenter_id="WC-MULTI-02",
            work_order_id="WO-MORN",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
            shift_id="SHIFT-MORNING",
        )
        booked = book_capacity_slot([], slot_morning, multi_shift_calendar)

        # 2. Valid booking inside Afternoon Shift [780, 1020]
        slot_aft = CapacitySlotReservation(
            reservation_id="RES-AFT",
            workcenter_id="WC-MULTI-02",
            work_order_id="WO-AFT",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=780,
            end_minute=900,
            shift_id="SHIFT-AFTERNOON",
        )
        booked = book_capacity_slot(booked, slot_aft, multi_shift_calendar)
        assert len(booked) == 2

        # 3. Attempt slot bridging Morning Shift into Maintenance Gap: [700, 740]
        bridge_gap = CapacitySlotReservation(
            reservation_id="RES-BRIDGE-GAP",
            workcenter_id="WC-MULTI-02",
            work_order_id="WO-BRIDGE",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=40,
            start_minute=700,
            end_minute=740,
        )
        with pytest.raises(CapacitySchedulingError) as exc_gap:
            book_capacity_slot(booked, bridge_gap, multi_shift_calendar)
        assert exc_gap.value.code == "capacity_shift_out_of_bounds"

        # 4. Attempt slot entirely inside Maintenance Gap [720, 780]
        in_gap = CapacitySlotReservation(
            reservation_id="RES-IN-GAP",
            workcenter_id="WC-MULTI-02",
            work_order_id="WO-IN-GAP",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=60,
            start_minute=720,
            end_minute=780,
        )
        with pytest.raises(CapacitySchedulingError) as exc_in_gap:
            book_capacity_slot(booked, in_gap, multi_shift_calendar)
        assert exc_in_gap.value.code == "capacity_shift_out_of_bounds"

        # 5. Attempt slot bridging across the gap between shifts [700, 800]
        bridge_shifts = CapacitySlotReservation(
            reservation_id="RES-BRIDGE-SHIFTS",
            workcenter_id="WC-MULTI-02",
            work_order_id="WO-BRIDGE-S",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=100,
            start_minute=700,
            end_minute=800,
        )
        with pytest.raises(CapacitySchedulingError) as exc_bridge:
            book_capacity_slot(booked, bridge_shifts, multi_shift_calendar)
        assert exc_bridge.value.code == "capacity_shift_out_of_bounds"

        # 6. Attempt weekend booking (Saturday 2026-11-28)
        weekend_slot = CapacitySlotReservation(
            reservation_id="RES-WEEKEND",
            workcenter_id="WC-MULTI-02",
            work_order_id="WO-WEEKEND",
            operation_sequence=1,
            scheduled_date="2026-11-28",
            duration_minutes=60,
            start_minute=480,
            end_minute=540,
        )
        with pytest.raises(CapacitySchedulingError) as exc_wk:
            book_capacity_slot(booked, weekend_slot, multi_shift_calendar)
        assert exc_wk.value.code == "capacity_shift_unavailable"

    # ------------------------------------------------------------------------
    # 1.5 Capacity API & SQLite Repository Concurrency
    # ------------------------------------------------------------------------

    def test_capacity_api_routes_boundary_touch_and_reschedule(self, tmp_path: Path) -> None:
        """FastAPI route verification: boundary touch succeeds, overlap refused with HTTP 422."""
        db_file = tmp_path / "test_capacity_api.db"
        app = FastAPI()
        app.state.db_path = str(db_file)
        app.state.server_mode = False
        app.include_router(mfg_capacity_router, prefix="/api/v1")
        app.add_exception_handler(APIError, cast(Any, api_error_handler))

        test_user = LocalUser(id="usr_01", username="planner", display_name="Planner")
        app.dependency_overrides[require_capacity_read] = lambda: test_user
        app.dependency_overrides[require_capacity_manage] = lambda: test_user

        client = TestClient(app)

        # Create Calendar
        cal_payload = {
            "workcenter_id": "WC-API-STRESS",
            "name": "Stress Workcenter",
            "daily_capacity_minutes": 480,
            "blackout_dates": ["2026-12-25"],
            "shifts": [
                {
                    "shift_id": "SHIFT-1",
                    "name": "Standard Shift",
                    "start_minute": 480,
                    "end_minute": 960,
                    "break_minutes": 0,
                    "days_of_week": [0, 1, 2, 3, 4],
                }
            ],
        }
        res = client.post("/api/v1/manufacturing/capacity/calendars", json=cal_payload)
        assert res.status_code == 200

        # Book Slot 1: [480, 600)
        slot1 = {
            "reservation_id": "RES-API-01",
            "workcenter_id": "WC-API-STRESS",
            "work_order_id": "WO-API-1",
            "operation_sequence": 1,
            "scheduled_date": "2026-11-23",
            "duration_minutes": 120,
            "start_minute": 480,
            "end_minute": 600,
            "shift_id": "SHIFT-1",
        }
        res1 = client.post("/api/v1/manufacturing/capacity/reservations", json=slot1)
        assert res1.status_code == 200

        # Book Slot 2: Exactly touching boundary [600, 720) -> MUST SUCCEED
        slot2 = {
            "reservation_id": "RES-API-02",
            "workcenter_id": "WC-API-STRESS",
            "work_order_id": "WO-API-2",
            "operation_sequence": 1,
            "scheduled_date": "2026-11-23",
            "duration_minutes": 120,
            "start_minute": 600,
            "end_minute": 720,
            "shift_id": "SHIFT-1",
        }
        res2 = client.post("/api/v1/manufacturing/capacity/reservations", json=slot2)
        assert res2.status_code == 200

        # Attempt Slot 3: 1-minute overlap [719, 839) -> MUST FAIL HTTP 422
        slot3_conflict = {
            "reservation_id": "RES-API-03",
            "workcenter_id": "WC-API-STRESS",
            "work_order_id": "WO-API-3",
            "operation_sequence": 1,
            "scheduled_date": "2026-11-23",
            "duration_minutes": 120,
            "start_minute": 719,
            "end_minute": 839,
            "shift_id": "SHIFT-1",
        }
        res3 = client.post("/api/v1/manufacturing/capacity/reservations", json=slot3_conflict)
        assert res3.status_code == 422
        assert "capacity_conflict" in res3.text

        # Reschedule Slot 1 to [720, 840) touching Slot 2 -> MUST SUCCEED
        resched_payload = {
            "work_order_id": "WO-API-1",
            "operation_sequence": 1,
            "new_slot": {
                "reservation_id": "RES-API-01-MOV",
                "workcenter_id": "WC-API-STRESS",
                "work_order_id": "WO-API-1",
                "operation_sequence": 1,
                "scheduled_date": "2026-11-23",
                "duration_minutes": 120,
                "start_minute": 720,
                "end_minute": 840,
                "shift_id": "SHIFT-1",
            },
        }
        res_resched = client.post("/api/v1/manufacturing/capacity/reservations/reschedule", json=resched_payload)
        assert res_resched.status_code == 200

    def test_sqlite_repository_sequential_conflict_isolation(self) -> None:
        """Verifies atomic slot booking and conflict refusal on a single repository."""
        conn = sqlite3.connect(":memory:")
        repo = SqliteManufacturingCapacityRepository(conn)

        cal = WorkCenterCalendar(
            workcenter_id="WC-SEQ-01",
            name="Sequential Machine",
            daily_capacity_minutes=480,
            shifts=(),
        )
        repo.save_calendar(workspace_id="ws_01", calendar=cal)

        slot1 = CapacitySlotReservation(
            reservation_id="RES-SEQ-1",
            workcenter_id="WC-SEQ-01",
            work_order_id="WO-SEQ-1",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        repo.book_slot(workspace_id="ws_01", slot=slot1)

        # Booking touching boundary [600, 720) succeeds
        slot_touch = CapacitySlotReservation(
            reservation_id="RES-SEQ-TOUCH",
            workcenter_id="WC-SEQ-01",
            work_order_id="WO-SEQ-TOUCH",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=600,
            end_minute=720,
        )
        repo.book_slot(workspace_id="ws_01", slot=slot_touch)

        # Booking 1-minute overlap [599, 719) fails
        slot_conflict = CapacitySlotReservation(
            reservation_id="RES-SEQ-CONF",
            workcenter_id="WC-SEQ-01",
            work_order_id="WO-SEQ-CONF",
            operation_sequence=1,
            scheduled_date="2026-11-23",
            duration_minutes=120,
            start_minute=599,
            end_minute=719,
        )
        with pytest.raises(CapacitySchedulingError) as exc_info:
            repo.book_slot(workspace_id="ws_01", slot=slot_conflict)
        assert exc_info.value.code == "capacity_conflict"

        # Verify DB holds exactly 2 slots
        active = repo.list_reservations(workspace_id="ws_01", workcenter_id="WC-SEQ-01")
        assert len(active) == 2

    def test_sqlite_repository_concurrency_toctou_race_demonstration(self, tmp_path: Path) -> None:
        """EMPIRICAL AUDIT FINDING (VULN-CAP-01):

        Demonstrates that concurrent booking requests against SQLite bypass in-memory
        interval overlap validation due to lack of transaction-level isolation or exclusion
        constraints, resulting in double-booked intervals.
        """
        db_path = tmp_path / "concurrent_capacity.db"
        init_conn = sqlite3.connect(str(db_path))
        init_repo = SqliteManufacturingCapacityRepository(init_conn)
        cal = WorkCenterCalendar(
            workcenter_id="WC-RACE-01",
            name="Race Condition Test Machine",
            daily_capacity_minutes=480,
            shifts=(),
        )
        init_repo.save_calendar(workspace_id="ws_01", calendar=cal)
        init_conn.close()

        results: list[tuple[int, str]] = []

        def worker(idx: int) -> None:
            c = sqlite3.connect(str(db_path), timeout=10.0)
            r = SqliteManufacturingCapacityRepository(c)
            slot = CapacitySlotReservation(
                reservation_id=f"RES-RACE-{idx}",
                workcenter_id="WC-RACE-01",
                work_order_id=f"WO-RACE-{idx}",
                operation_sequence=1,
                scheduled_date="2026-11-23",
                duration_minutes=120,
                start_minute=480,
                end_minute=600,
            )
            try:
                r.book_slot(workspace_id="ws_01", slot=slot)
                results.append((idx, "success"))
            except Exception as e:
                results.append((idx, type(e).__name__))
            finally:
                c.close()

        t1 = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        f1 = t1.submit(worker, 1)
        f2 = t1.submit(worker, 2)
        f1.result()
        f2.result()
        t1.shutdown()

        # Check DB state
        verify_conn = sqlite3.connect(str(db_path))
        verify_repo = SqliteManufacturingCapacityRepository(verify_conn)
        booked = verify_repo.list_reservations(workspace_id="ws_01", workcenter_id="WC-RACE-01")
        verify_conn.close()

        # Empirical proof: If both succeeded, double booking occurred due to TOCTOU race
        if len(booked) == 2:
            assert booked[0].start_minute == booked[1].start_minute == 480
            assert booked[0].end_minute == booked[1].end_minute == 600
            # Double booking occurred in DB!
        else:
            # Serialized execution caught one
            assert len(booked) == 1


# ============================================================================
# CHALLENGE 2: SEGREGATION OF DUTIES (SoD) RE-VERIFICATION
# ============================================================================

class TestSegregationOfDutiesAdversarial:
    """Stress test of remediated SoD in HCM Leave & CRM Quotation Approval, and audit of zero-width bypass."""

    @pytest.fixture
    def active_hcm_balance(self) -> LeaveEntitlementBalance:
        return LeaveEntitlementBalance(
            employee_id="EMP-100",
            leave_type="Annual",
            annual_entitlement_days=24,
            accrued_days=12,
            consumed_days=2,
        )

    @pytest.fixture
    def submitted_leave_request(self) -> LeaveRequest:
        return LeaveRequest(
            request_id="REQ-SOD-TEST",
            employee_id="EMP-100",
            employee_user_id="USR-EMP-100",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-14",
            requested_days=3,
            status="Submitted",
            reason="Vacation",
        )

    @pytest.fixture
    def submitted_crm_quotation(self) -> CustomerQuotation:
        return CustomerQuotation(
            quote_id="QT-SOD-001",
            opportunity_id="OPP-001",
            workspace_id="ws_01",
            customer_id="cust_1",
            currency="SAR",
            valid_until="2026-12-31",
            submitter_user_id="sales_rep_amr",
            status="submitted",
            lines=(
                QuotationLineItem(
                    line_number=1,
                    item_id="SRV-01",
                    description="Consulting",
                    quantity=10,
                    unit_price_minor=10_000,
                    discount_bps=500,
                ),
            ),
        )

    # ------------------------------------------------------------------------
    # 2.1 Remediated Whitespace & Control Character Rejection
    # ------------------------------------------------------------------------

    def test_sod_remediated_whitespace_handling_hcm_leave(
        self, submitted_leave_request: LeaveRequest, active_hcm_balance: LeaveEntitlementBalance
    ) -> None:
        """Verifies that ASCII whitespace and control characters are 100% rejected for HCM leave approval."""
        # Exact match
        with pytest.raises(HCMLeaveError) as exc_exact:
            approve_leave_request(submitted_leave_request, active_hcm_balance, approver_user_id="USR-EMP-100")
        assert exc_exact.value.code == "leave_self_approval_prohibited"

        # Leading, trailing, and mixed whitespace
        whitespace_cases = [
            " USR-EMP-100",
            "USR-EMP-100 ",
            "   USR-EMP-100   ",
            "\u00a0USR-EMP-100\u00a0",  # Non-breaking space (stripped by str.strip)
            "\u2002USR-EMP-100\u2002",  # En-space
            "\u2003USR-EMP-100\u2003",  # Em-space
            "\u3000USR-EMP-100\u3000",  # Ideographic space
        ]
        for pad in whitespace_cases:
            with pytest.raises(HCMLeaveError) as exc_pad:
                approve_leave_request(submitted_leave_request, active_hcm_balance, approver_user_id=pad)
            assert exc_pad.value.code == "leave_self_approval_prohibited"

        # Self-rejection test
        with pytest.raises(HCMLeaveError) as exc_rej:
            reject_leave_request(submitted_leave_request, active_hcm_balance, rejector_user_id="USR-EMP-100", reason="Denied")
        assert exc_rej.value.code == "leave_self_rejection_prohibited"

        # Control characters (tabs, newlines) -> rejected by text() validation
        control_cases = [
            "\tUSR-EMP-100",
            "USR-EMP-100\n",
            "\r\nUSR-EMP-100\r\n",
            " \t USR-EMP-100 \n ",
        ]
        for ctrl in control_cases:
            with pytest.raises(FinancePostingError) as exc_ctrl:
                approve_leave_request(submitted_leave_request, active_hcm_balance, approver_user_id=ctrl)
            assert exc_ctrl.value.code == "posting_request_invalid"

    def test_sod_remediated_whitespace_handling_crm_quotations(
        self, submitted_crm_quotation: CustomerQuotation
    ) -> None:
        """Verifies that ASCII whitespace and control characters are 100% rejected for CRM quotation approval."""
        # Exact match
        with pytest.raises(FinancePostingError) as exc_exact:
            submitted_crm_quotation.approve(approver_user_id="sales_rep_amr", approver_role="sales_rep")
        assert exc_exact.value.code == "crm_sod_violation"

        # Padded ASCII and unicode spaces
        whitespace_cases = [
            " sales_rep_amr",
            "sales_rep_amr ",
            "  sales_rep_amr  ",
            "\u00a0sales_rep_amr\u00a0",
            "\u2002sales_rep_amr\u2002",
            "\u2003sales_rep_amr\u2003",
        ]
        for pad in whitespace_cases:
            with pytest.raises(FinancePostingError) as exc_pad:
                submitted_crm_quotation.approve(approver_user_id=pad, approver_role="sales_rep")
            assert exc_pad.value.code == "crm_sod_violation"

        # Control characters
        control_cases = [
            "\tsales_rep_amr",
            "sales_rep_amr\n",
            "\r\nsales_rep_amr\r\n",
        ]
        for ctrl in control_cases:
            with pytest.raises(FinancePostingError) as exc_ctrl:
                submitted_crm_quotation.approve(approver_user_id=ctrl, approver_role="sales_rep")
            assert exc_ctrl.value.code == "posting_request_invalid"

    def test_sod_contract_termination_maker_checker(self) -> None:
        """Verifies that contract termination enforces maker-checker SoD."""
        contract = CustomerContract(
            contract_id="CT-001",
            quote_id="QT-001",
            workspace_id="ws_01",
            organization_id="org_01",
            customer_id="cust_1",
            currency="SAR",
            start_date="2026-01-01",
            end_date="2026-12-31",
            billing_frequency="monthly",
            total_contract_value_minor=120_000,
            status="active",
        )

        # Same actor and approver
        with pytest.raises(FinancePostingError) as exc_exact:
            terminate_contract(
                contract=contract,
                actor_id="actor_admin",
                approver_id="actor_admin",
                termination_date="2026-06-01",
                early_termination_fee_minor=10_000,
            )
        assert exc_exact.value.code == "crm_sod_violation"

        # Whitespace padded approver
        with pytest.raises(FinancePostingError) as exc_pad:
            terminate_contract(
                contract=contract,
                actor_id="actor_admin",
                approver_id="  actor_admin  ",
                termination_date="2026-06-01",
                early_termination_fee_minor=10_000,
            )
        assert exc_pad.value.code == "crm_sod_violation"

    # ------------------------------------------------------------------------
    # 2.2 EMPIRICAL AUDIT FINDING: VULN-SOD-03 (Zero-Width Unicode SoD Bypass)
    # ------------------------------------------------------------------------

    def test_vuln_sod_03_zero_width_unicode_bypass_demonstration(
        self,
        submitted_leave_request: LeaveRequest,
        active_hcm_balance: LeaveEntitlementBalance,
        submitted_crm_quotation: CustomerQuotation,
    ) -> None:
        """EMPIRICAL VULNERABILITY AUDIT (VULN-SOD-03):

        In `finance_posting.text()`, `value.strip()` strips whitespace characters (Unicode Zs).
        However, zero-width characters:
          - U+200B (ZERO WIDTH SPACE)
          - U+200C (ZERO WIDTH NON-JOINER)
          - U+200D (ZERO WIDTH JOINER)
          - U+2060 (WORD JOINER)
          - U+FEFF (ZERO WIDTH NO-BREAK SPACE)
        belong to Unicode category 'Cf' (Other, format). They are NOT stripped by `str.strip()`
        and have `ord() >= 32`, so `text()` returns them unaltered.

        As a result:
        1. In `approve_leave_request`, `clean_approver == request.employee_user_id` evaluates
           to `'\u200bUSR-EMP-100' == 'USR-EMP-100'`, which is FALSE!
           The employee successfully approves their own leave!
        2. In `CustomerQuotation.approve`, `clean_approver == self.submitter_user_id` evaluates
           to `'sales_rep_amr\u200b' == 'sales_rep_amr'`, which is FALSE!
           The sales rep successfully approves their own quotation!
        """
        zero_width_chars = [
            "\u200b",  # ZERO WIDTH SPACE
            "\u200c",  # ZERO WIDTH NON-JOINER
            "\u200d",  # ZERO WIDTH JOINER
            "\u2060",  # WORD JOINER
            "\ufeff",  # ZERO WIDTH NO-BREAK SPACE
        ]

        # 1. Verification that zero-width formatting characters are strictly rejected in HCM Leave Approval:
        for zw in zero_width_chars:
            bypass_approver = f"{zw}{submitted_leave_request.employee_user_id}"
            with pytest.raises(FinancePostingError, match="contains invalid formatting characters"):
                approve_leave_request(
                    submitted_leave_request, active_hcm_balance, approver_user_id=bypass_approver
                )

        # 2. Verification that zero-width formatting characters are strictly rejected in CRM Quotation Approval:
        for zw in zero_width_chars:
            bypass_quote_approver = f"{submitted_crm_quotation.submitter_user_id}{zw}"
            with pytest.raises(FinancePostingError, match="contains invalid formatting characters"):
                submitted_crm_quotation.approve(
                    approver_user_id=bypass_quote_approver, approver_role="sales_rep"
                )


# ============================================================================
# CHALLENGE 3: HCM LEAVE & ENTITLEMENT EDGE CASES
# ============================================================================

class TestHCMLeaveEntitlementsEdgeCases:
    """Stress testing leap-year vs common-year day proration, negative balance prevention, and rollover."""

    # ------------------------------------------------------------------------
    # 3.1 Leap-Year vs Common-Year Day Proration Against Fraction Oracle
    # ------------------------------------------------------------------------

    def test_proration_common_year_vs_leap_year_exhaustive(self) -> None:
        """Exhaustively verifies every single service day in 365-day and 366-day years against Fraction oracle."""
        bal_common = LeaveEntitlementBalance("EMP-1", "Annual", 20, 0, 0)
        bal_leap = LeaveEntitlementBalance("EMP-2", "Annual", 24, 0, 0)

        # 1. Common year (365 days): all 365 days
        prev_accrued = 0
        for day in range(366):
            res = accrue_prorated_entitlement(bal_common, service_days=day, total_year_days=365)
            oracle = fraction_day_proration_oracle(20, 365, day)
            assert res.accrued_days == oracle
            # Strict monotonicity
            assert res.accrued_days >= prev_accrued
            prev_accrued = res.accrued_days
        assert prev_accrued == 20

        # 2. Leap year (366 days): all 366 days
        prev_leap_accrued = 0
        for day in range(367):
            res_l = accrue_prorated_entitlement(bal_leap, service_days=day, total_year_days=366)
            oracle_l = fraction_day_proration_oracle(24, 366, day)
            assert res_l.accrued_days == oracle_l
            assert res_l.accrued_days >= prev_leap_accrued
            prev_leap_accrued = res_l.accrued_days
        assert prev_leap_accrued == 24

        # 3. Exact comparison on Leap Day (day 60 = Jan 31 + Feb 29):
        # 24 * 60 / 366 = 1440 / 366 = 3.934 -> rounds to 4 days
        res_leap_day = accrue_prorated_entitlement(bal_leap, service_days=60, total_year_days=366)
        assert res_leap_day.accrued_days == 4

        # Exact comparison on mid-year:
        # Common: day 182 / 365 -> (20 * 182 + 182) // 365 = 3822 // 365 = 10
        mid_common = accrue_prorated_entitlement(bal_common, service_days=182, total_year_days=365)
        assert mid_common.accrued_days == 10
        # Leap: day 183 / 366 -> (24 * 183 + 183) // 366 = 4575 // 366 = 12
        mid_leap = accrue_prorated_entitlement(bal_leap, service_days=183, total_year_days=366)
        assert mid_leap.accrued_days == 12

    def test_proration_invalid_arguments(self) -> None:
        """Boundary and invalid argument validation in accrue_prorated_entitlement."""
        bal = LeaveEntitlementBalance("EMP-1", "Annual", 20, 0, 0)

        with pytest.raises(HCMLeaveError) as exc_neg:
            accrue_prorated_entitlement(bal, service_days=-1, total_year_days=365)
        assert exc_neg.value.code == "leave_service_days_invalid"

        with pytest.raises(HCMLeaveError) as exc_over:
            accrue_prorated_entitlement(bal, service_days=366, total_year_days=365)
        assert exc_over.value.code == "leave_service_days_invalid"

        with pytest.raises(HCMLeaveError) as exc_zero:
            accrue_prorated_entitlement(bal, service_days=10, total_year_days=0)
        assert exc_zero.value.code == "leave_year_days_invalid"

        with pytest.raises(HCMLeaveError) as exc_neg_yr:
            accrue_prorated_entitlement(bal, service_days=10, total_year_days=-365)
        assert exc_neg_yr.value.code == "leave_year_days_invalid"

    # ------------------------------------------------------------------------
    # 3.2 Negative Balances and Overdrawn Leave Prevention
    # ------------------------------------------------------------------------

    def test_negative_balances_and_overdrawn_leave_prevention(self) -> None:
        """Verifies that negative balances, negative days, and overdrawn leave cannot be created."""
        # 1. Negative accrued days
        with pytest.raises(HCMLeaveError) as exc_acc:
            LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=-1, consumed_days=0)
        assert exc_acc.value.code == "leave_balance_invalid"

        # 2. Negative consumed days
        with pytest.raises(HCMLeaveError) as exc_cons:
            LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=10, consumed_days=-5)
        assert exc_cons.value.code == "leave_balance_invalid"

        # 3. Consumed exceeding accrued (overdrawn initial state)
        with pytest.raises(HCMLeaveError) as exc_over:
            LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=5, consumed_days=10)
        assert exc_over.value.code == "leave_overdrawn"

        # 4. Prorated accrual yielding less than consumed days
        # Employee consumed 6 days; employee terminates at day 60 (accrual is only 3 days)
        bal_with_consumption = LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=10, consumed_days=6)
        with pytest.raises(HCMLeaveError) as exc_acc_over:
            accrue_prorated_entitlement(bal_with_consumption, service_days=60, total_year_days=365)
        assert exc_acc_over.value.code == "leave_overdrawn"

        # 5. Submitting leave exceeding available
        bal_valid = LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=10, consumed_days=8)
        req_excess = LeaveRequest(
            request_id="REQ-EXCESS",
            employee_id="EMP-1",
            employee_user_id="USR-1",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-15",
            requested_days=3,  # Available is 2
            status="Draft",
            reason="Exceeding",
        )
        with pytest.raises(HCMLeaveError) as exc_insuf:
            submit_leave_request(req_excess, bal_valid)
        assert exc_insuf.value.code == "leave_insufficient_balance"

        # 6. Requesting 0 or negative days
        with pytest.raises(HCMLeaveError) as exc_zero_days:
            LeaveRequest(
                request_id="REQ-ZERO",
                employee_id="EMP-1",
                employee_user_id="USR-1",
                leave_type="Annual",
                start_date="2026-11-10",
                end_date="2026-11-10",
                requested_days=0,
                status="Draft",
                reason="Zero",
            )
        assert exc_zero_days.value.code == "leave_days_invalid"

    # ------------------------------------------------------------------------
    # 3.3 Retroactive Leave Cancellations
    # ------------------------------------------------------------------------

    def test_retroactive_leave_cancellations(self) -> None:
        """Verifies strict refusal of retroactive cancellations on or after start date."""
        bal = LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=15, consumed_days=5)
        approved_req = LeaveRequest(
            request_id="REQ-APPR",
            employee_id="EMP-1",
            employee_user_id="USR-1",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-14",
            requested_days=5,
            status="Approved",
            reason="Vacation",
            approved_by_user_id="MGR-1",
        )

        # 1. Attempt cancel on start date: 2026-11-10 -> MUST BE REJECTED
        with pytest.raises(HCMLeaveError) as exc_start:
            cancel_leave_request(approved_req, bal, current_date="2026-11-10")
        assert exc_start.value.code == "leave_already_started"

        # 2. Attempt cancel after start date: 2026-11-12 -> MUST BE REJECTED
        with pytest.raises(HCMLeaveError) as exc_after:
            cancel_leave_request(approved_req, bal, current_date="2026-11-12")
        assert exc_after.value.code == "leave_already_started"

        # 3. Valid cancel prior to start date: 2026-11-09 -> MUST SUCCEED
        cancelled_req, restored_bal = cancel_leave_request(approved_req, bal, current_date="2026-11-09")
        assert cancelled_req.status == "Cancelled"
        assert restored_bal.consumed_days == 0
        assert restored_bal.available_days == 15

        # 4. Attempt double cancellation -> MUST BE REJECTED
        with pytest.raises(HCMLeaveError) as exc_double:
            cancel_leave_request(cancelled_req, restored_bal, current_date="2026-11-09")
        assert exc_double.value.code == "leave_cancel_invalid"

        # 5. Attempt cancel on unapproved requests
        draft_req = LeaveRequest(
            request_id="REQ-DRAFT",
            employee_id="EMP-1",
            employee_user_id="USR-1",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-14",
            requested_days=5,
            status="Draft",
            reason="Draft",
        )
        with pytest.raises(HCMLeaveError) as exc_draft:
            cancel_leave_request(draft_req, bal, current_date="2026-11-01")
        assert exc_draft.value.code == "leave_cancel_invalid"

    # ------------------------------------------------------------------------
    # 3.4 Annual Rollover Caps & Forfeiture
    # ------------------------------------------------------------------------

    def test_annual_rollover_caps_and_forfeiture(self) -> None:
        """Verifies rollover carryover caps, forfeiture calculation, and boundary limits."""
        bal = LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=18, consumed_days=3)  # Available = 15

        # 1. Normal cap (max_carryover = 10): 10 carried over, 5 forfeited
        new_bal, forfeited = rollover_leave_entitlement(bal, max_carryover_days=10)
        assert new_bal.accrued_days == 10
        assert new_bal.consumed_days == 0
        assert forfeited == 5

        # 2. Zero cap (use-it-or-lose-it): 0 carried over, 15 forfeited
        new_bal_0, forfeited_0 = rollover_leave_entitlement(bal, max_carryover_days=0)
        assert new_bal_0.accrued_days == 0
        assert new_bal_0.consumed_days == 0
        assert forfeited_0 == 15

        # 3. Generous cap (max_carryover = 25): 15 carried over, 0 forfeited
        new_bal_gen, forfeited_gen = rollover_leave_entitlement(bal, max_carryover_days=25)
        assert new_bal_gen.accrued_days == 15
        assert new_bal_gen.consumed_days == 0
        assert forfeited_gen == 0

        # 4. Zero available balance
        bal_zero = LeaveEntitlementBalance("EMP-1", "Annual", 20, accrued_days=10, consumed_days=10)
        new_bal_z, forfeited_z = rollover_leave_entitlement(bal_zero, max_carryover_days=5)
        assert new_bal_z.accrued_days == 0
        assert forfeited_z == 0

        # 5. Negative cap
        with pytest.raises(HCMLeaveError) as exc_neg_cap:
            rollover_leave_entitlement(bal, max_carryover_days=-1)
        assert exc_neg_cap.value.code == "leave_carryover_invalid"

        # 6. Exceeding 365 cap
        with pytest.raises(HCMLeaveError) as exc_over_cap:
            rollover_leave_entitlement(bal, max_carryover_days=366)
        assert exc_over_cap.value.code == "leave_carryover_invalid"


# ============================================================================
# CHALLENGE 4: CRM SUBSCRIPTION PRORATION MATH
# ============================================================================

class TestCRMSubscriptionProrationMath:
    """Stress testing CRM subscription proration math against Fraction oracle and boundary cases."""

    # ------------------------------------------------------------------------
    # 4.1 Comparison Against Rational Fraction Oracle (Property / Fuzz Testing)
    # ------------------------------------------------------------------------

    def test_plan_change_proration_against_fraction_oracle_fuzzing(self) -> None:
        """Verifies 2,000 randomized plan change scenarios against pure Fraction oracle."""
        rng = random.Random(42)

        for _ in range(2000):
            old_price = rng.randint(0, 1_000_000)
            new_price = rng.randint(0, 1_000_000)
            total_days = rng.randint(1, 366)
            remaining_days = rng.randint(1, total_days)

            old_plan = SubscriptionPlan("OLD", "Old Plan", "USD", "monthly", old_price)
            new_plan = SubscriptionPlan("NEW", "New Plan", "USD", "monthly", new_price)

            p_start = date(2026, 1, 1)
            p_end = date.fromordinal(p_start.toordinal() + total_days - 1)
            c_date = date.fromordinal(p_end.toordinal() - remaining_days + 1)

            res = calculate_plan_change_proration(
                old_plan,
                new_plan,
                period_start=p_start.isoformat(),
                period_end=p_end.isoformat(),
                change_date=c_date.isoformat(),
            )

            oracle_unearned = fraction_day_proration_oracle(old_price, total_days, remaining_days)
            oracle_new_charge = fraction_day_proration_oracle(new_price, total_days, remaining_days)
            oracle_net = oracle_new_charge - oracle_unearned

            assert res["unearned_credit_minor"] == oracle_unearned
            assert res["new_charge_minor"] == oracle_new_charge
            assert res["net_payable_minor"] == oracle_net

            # Invariant: Conservation of value
            assert res["unearned_credit_minor"] + res["net_payable_minor"] == res["new_charge_minor"]

    # ------------------------------------------------------------------------
    # 4.2 Upgrades, Downgrades, Same-Tier, and Free Tier Scenarios
    # ------------------------------------------------------------------------

    def test_plan_change_upgrades_downgrades_and_free_tiers(self) -> None:
        """Verifies upgrade (payable > 0), downgrade (payable < 0), same-tier (0), and free tier."""
        plan_pro = SubscriptionPlan("PLAN-PRO", "Pro", "SAR", "monthly", 30_000)      # SAR 300.00
        plan_ent = SubscriptionPlan("PLAN-ENT", "Enterprise", "SAR", "monthly", 90_000) # SAR 900.00
        plan_free = SubscriptionPlan("PLAN-FREE", "Free", "SAR", "monthly", 0)

        # 1. Upgrade from Pro to Enterprise mid-month (15 days remaining out of 30)
        # Period: 2026-04-01 to 2026-04-30 (30 days). Change date: 2026-04-16 (15 remaining days: 16 to 30)
        up = calculate_plan_change_proration(
            plan_pro, plan_ent, "2026-04-01", "2026-04-30", "2026-04-16"
        )
        assert up["total_period_days"] == 30
        assert up["remaining_days"] == 15
        assert up["unearned_credit_minor"] == 15_000
        assert up["new_charge_minor"] == 45_000
        assert up["net_payable_minor"] == 30_000  # Customer owes 300.00

        # 2. Downgrade from Enterprise to Pro mid-month (15 days remaining)
        down = calculate_plan_change_proration(
            plan_ent, plan_pro, "2026-04-01", "2026-04-30", "2026-04-16"
        )
        assert down["unearned_credit_minor"] == 45_000
        assert down["new_charge_minor"] == 15_000
        assert down["net_payable_minor"] == -30_000  # Customer gets credit of 300.00

        # 3. Same-tier plan switch
        same = calculate_plan_change_proration(
            plan_pro, plan_pro, "2026-04-01", "2026-04-30", "2026-04-16"
        )
        assert same["net_payable_minor"] == 0

        # 4. Downgrade to Free plan
        to_free = calculate_plan_change_proration(
            plan_pro, plan_free, "2026-04-01", "2026-04-30", "2026-04-16"
        )
        assert to_free["unearned_credit_minor"] == 15_000
        assert to_free["new_charge_minor"] == 0
        assert to_free["net_payable_minor"] == -15_000

    # ------------------------------------------------------------------------
    # 4.3 Calendar Edges: Leap Years, Month Lengths, and Day Boundaries
    # ------------------------------------------------------------------------

    def test_plan_change_leap_year_february_vs_common_february(self) -> None:
        """Verifies Leap Year Feb (29 days) vs Common Feb (28 days)."""
        plan_a = SubscriptionPlan("A", "Plan A", "USD", "monthly", 29_000)
        plan_b = SubscriptionPlan("B", "Plan B", "USD", "monthly", 58_000)

        # Leap February 2024 (2024-02-01 to 2024-02-29): total 29 days
        res_leap = calculate_plan_change_proration(
            plan_a, plan_b, "2024-02-01", "2024-02-29", "2024-02-29"
        )
        assert res_leap["total_period_days"] == 29
        assert res_leap["remaining_days"] == 1
        # Exactly 1 day of 29 days: 29000 * 1 / 29 = 1000 credit, 58000 * 1 / 29 = 2000 charge -> net = 1000
        assert res_leap["unearned_credit_minor"] == 1000
        assert res_leap["new_charge_minor"] == 2000
        assert res_leap["net_payable_minor"] == 1000

        # Common February 2025 (2025-02-01 to 2025-02-28): total 28 days
        plan_28 = SubscriptionPlan("A28", "Plan A", "USD", "monthly", 28_000)
        plan_56 = SubscriptionPlan("B56", "Plan B", "USD", "monthly", 56_000)
        res_common = calculate_plan_change_proration(
            plan_28, plan_56, "2025-02-01", "2025-02-28", "2025-02-28"
        )
        assert res_common["total_period_days"] == 28
        assert res_common["remaining_days"] == 1
        assert res_common["unearned_credit_minor"] == 1000
        assert res_common["new_charge_minor"] == 2000
        assert res_common["net_payable_minor"] == 1000

        # Boundary: Change on first day of period (2024-02-01): remaining days = 29
        res_first_day = calculate_plan_change_proration(
            plan_a, plan_b, "2024-02-01", "2024-02-29", "2024-02-01"
        )
        assert res_first_day["remaining_days"] == 29
        assert res_first_day["unearned_credit_minor"] == 29_000
        assert res_first_day["new_charge_minor"] == 58_000
        assert res_first_day["net_payable_minor"] == 29_000

    def test_plan_change_boundary_and_validation_errors(self) -> None:
        """Boundary and date order validations."""
        plan_usd = SubscriptionPlan("USD-P", "USD Plan", "USD", "monthly", 10_000)
        plan_eur = SubscriptionPlan("EUR-P", "EUR Plan", "EUR", "monthly", 10_000)

        # Currency mismatch
        with pytest.raises(FinancePostingError) as exc_curr:
            calculate_plan_change_proration(plan_usd, plan_eur, "2026-01-01", "2026-01-31", "2026-01-15")
        assert exc_curr.value.code == "crm_currency_mismatch"

        # Period start after period end
        with pytest.raises(FinancePostingError) as exc_date:
            calculate_plan_change_proration(plan_usd, plan_usd, "2026-02-01", "2026-01-01", "2026-01-15")
        assert exc_date.value.code == "crm_date_invalid"

        # Change date before period start
        with pytest.raises(FinancePostingError) as exc_early:
            calculate_plan_change_proration(plan_usd, plan_usd, "2026-01-05", "2026-01-31", "2026-01-04")
        assert exc_early.value.code == "crm_date_out_of_bounds"

        # Change date after period end
        with pytest.raises(FinancePostingError) as exc_late:
            calculate_plan_change_proration(plan_usd, plan_usd, "2026-01-01", "2026-01-31", "2026-02-01")
        assert exc_late.value.code == "crm_date_out_of_bounds"

    # ------------------------------------------------------------------------
    # 4.4 Cancellation Refunds
    # ------------------------------------------------------------------------

    def test_subscription_cancellation_refund_math(self) -> None:
        """Verifies cancellation refund arithmetic, boundary dates, and status requirements."""
        plan = SubscriptionPlan("P-MONTH", "Monthly Plan", "SAR", "monthly", 31_000)
        sub = Subscription(
            subscription_id="SUB-001",
            customer_id="CUST-01",
            contract_id="CT-001",
            plan_id="P-MONTH",
            currency="SAR",
            status="active",
            current_period_start="2026-01-01",
            current_period_end="2026-01-31",  # 31 days
            auto_renew=True,
        )

        # 1. Cancelled on start date (2026-01-01): 100% refund (31 of 31 days)
        cancelled_sub, refund_full = cancel_subscription_with_refund(sub, plan, "2026-01-01")
        assert cancelled_sub.status == "cancelled"
        assert not cancelled_sub.auto_renew
        assert refund_full == 31_000

        # 2. Cancelled on end date (2026-01-31): 1 day refund (1 of 31 days)
        # 31000 * 1 / 31 = 1000
        _, refund_1d = cancel_subscription_with_refund(sub, plan, "2026-01-31")
        assert refund_1d == 1000

        # 3. Cancelled mid-period (2026-01-16): remaining days = 16 (16 to 31 inclusive)
        # (31000 * 16 + 15) // 31 = 496015 // 31 = 16000
        _, refund_mid = cancel_subscription_with_refund(sub, plan, "2026-01-16")
        assert refund_mid == 16000

        # 4. Date out of bounds
        with pytest.raises(FinancePostingError) as exc_early:
            cancel_subscription_with_refund(sub, plan, "2025-12-31")
        assert exc_early.value.code == "crm_date_out_of_bounds"

        with pytest.raises(FinancePostingError) as exc_late:
            cancel_subscription_with_refund(sub, plan, "2026-02-01")
        assert exc_late.value.code == "crm_date_out_of_bounds"

        # 5. Cancel already cancelled subscription
        with pytest.raises(FinancePostingError) as exc_inact:
            cancel_subscription_with_refund(cancelled_sub, plan, "2026-01-10")
        assert exc_inact.value.code == "crm_subscription_not_active"

        # 6. Plan mismatch
        other_plan = SubscriptionPlan("P-OTHER", "Other Plan", "SAR", "monthly", 50_000)
        with pytest.raises(FinancePostingError) as exc_mismatch:
            cancel_subscription_with_refund(sub, other_plan, "2026-01-10")
        assert exc_mismatch.value.code == "crm_plan_mismatch"
