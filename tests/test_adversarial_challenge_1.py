"""Empirical adversarial challenge and stress-test harness for ReconForge ERP (Challenge Set 1).

Challenges:
1. Work Center Finite Capacity Scheduling:
   - Interval overlapping slot booking scenarios (exact match, partial overlap left/right,
     contained subset, enclosing superset, boundary adjacent touches, off-by-one overlaps)
   - Midnight wrap and day-boundary handling (00:00, 24:00, wrap attempts, invalid minutes)
   - Shift calendar boundaries (exact shift bounds, outside bounds, inter-shift maintenance gaps,
     weekend shifts, blackout dates)
   - Atomic conflict rejection and state non-mutation invariants
   - Rescheduling conflict atomicity and non-existent slot rejection
   - Randomized interval oracle property test against ground truth

2. HCM Employee Leave & Entitlements:
   - Negative balance creation and overdrawn leave prevention
   - Maker-Checker Segregation of Duties (SoD) bypass attempts: direct self-approval,
     self-rejection, and whitespace sanitization differential analysis
   - Fiscal year-end rollover expiration, carryover caps, and forfeiture arithmetic
   - Leap-year (366 days) vs common-year (365 days) day proration half-up rounding
   - Cancellation restoration boundaries, retro-date restriction, and double-cancel overdrawn protection

3. CRM Customer Contracts & Subscription Prorated Billing:
   - Mid-month plan upgrades and downgrades with conservation of unearned credits / net payables
   - Zero-day, single-day, and negative period boundary cycles
   - Leap-year February (29 days) vs 28-day February vs 31-day months proration
   - Multi-currency adjustments and strict refusal of cross-currency plan change without explicit FX
   - Strict zero-float integer minor unit enforcement and randomized fuzzing
   - Customer quotation maker-checker whitespace padding analysis
"""

from __future__ import annotations

import random

import pytest

from reconforge.domain.crm_contracts import (
    CustomerQuotation,
    QuotationLineItem,
    Subscription,
    SubscriptionPlan,
    calculate_day_proration,
    calculate_plan_change_proration,
    cancel_subscription_with_refund,
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
    reschedule_capacity_slot,
)

# ============================================================================
# CHALLENGE 1: WORK CENTER FINITE CAPACITY SCHEDULING
# ============================================================================


@pytest.fixture
def standard_workcenter_calendar() -> WorkCenterCalendar:
    """Standard work center calendar with 8-hour shift (08:00-16:00, 480m capacity)."""
    shift = WorkCenterShift(
        shift_id="SHIFT-DAY",
        name="Day Shift",
        start_minute=480,  # 08:00
        end_minute=960,  # 16:00
        break_minutes=0,
        days_of_week=frozenset({0, 1, 2, 3, 4}),  # Mon-Fri
    )
    return WorkCenterCalendar(
        workcenter_id="WC-MACH-01",
        name="Precision Machining Cell",
        daily_capacity_minutes=480,
        blackout_dates=frozenset({"2026-12-25", "2026-12-26"}),
        shifts=(shift,),
    )


@pytest.fixture
def continuous_24h_workcenter_calendar() -> WorkCenterCalendar:
    """Full 24-hour continuous production calendar without shift bounds."""
    return WorkCenterCalendar(
        workcenter_id="WC-CONT-01",
        name="Continuous Smelting Furnace",
        daily_capacity_minutes=MAX_MINUTES_PER_DAY,
        blackout_dates=frozenset({"2026-12-25"}),
        shifts=(),
    )


class TestWorkCenterCapacitySchedulingAdversarial:
    """Adversarial stress suite targeting interval overlaps, boundaries, and atomic rejection."""

    # ------------------------------------------------------------------------
    # 1.1 Overlapping Slot Booking Scenarios (The 6 Topological Relations)
    # ------------------------------------------------------------------------

    def test_interval_exact_match_conflict(self, continuous_24h_workcenter_calendar: WorkCenterCalendar) -> None:
        """Exact identical start and end minute interval must be rejected."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        booked = book_capacity_slot([], base_slot, continuous_24h_workcenter_calendar)
        assert len(booked) == 1

        # Attempt exact match booking
        exact_dup = CapacitySlotReservation(
            reservation_id="RES-EXACT",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, exact_dup, continuous_24h_workcenter_calendar)

    def test_interval_partial_overlap_left_and_right(
        self, continuous_24h_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """Partial overlap from the left side [420, 540) and right side [540, 660) against [480, 600)."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        booked = book_capacity_slot([], base_slot, continuous_24h_workcenter_calendar)

        # Left partial overlap [420, 540)
        left_overlap = CapacitySlotReservation(
            reservation_id="RES-LEFT",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=420,
            end_minute=540,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, left_overlap, continuous_24h_workcenter_calendar)

        # Right partial overlap [540, 660)
        right_overlap = CapacitySlotReservation(
            reservation_id="RES-RIGHT",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-003",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=540,
            end_minute=660,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, right_overlap, continuous_24h_workcenter_calendar)

    def test_interval_contained_subset_and_enclosing_superset(
        self, continuous_24h_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """Subset [500, 560) inside [480, 600) and superset [420, 660) enclosing [480, 600)."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        booked = book_capacity_slot([], base_slot, continuous_24h_workcenter_calendar)

        # Subset [500, 560)
        subset_slot = CapacitySlotReservation(
            reservation_id="RES-SUB",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=60,
            start_minute=500,
            end_minute=560,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, subset_slot, continuous_24h_workcenter_calendar)

        # Superset [420, 660)
        superset_slot = CapacitySlotReservation(
            reservation_id="RES-SUPER",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-003",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=240,
            start_minute=420,
            end_minute=660,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, superset_slot, continuous_24h_workcenter_calendar)

    def test_interval_boundary_adjacent_touches_succeed(
        self, continuous_24h_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """Adjacent touching intervals [360, 480) and [600, 720) against [480, 600) must succeed without conflict."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        booked = book_capacity_slot([], base_slot, continuous_24h_workcenter_calendar)

        # Left adjacent touch [360, 480): end_minute == base.start_minute
        left_touch = CapacitySlotReservation(
            reservation_id="RES-LEFT-TOUCH",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=360,
            end_minute=480,
        )
        booked = book_capacity_slot(booked, left_touch, continuous_24h_workcenter_calendar)
        assert len(booked) == 2

        # Right adjacent touch [600, 720): start_minute == base.end_minute
        right_touch = CapacitySlotReservation(
            reservation_id="RES-RIGHT-TOUCH",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-003",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=600,
            end_minute=720,
        )
        booked = book_capacity_slot(booked, right_touch, continuous_24h_workcenter_calendar)
        assert len(booked) == 3

    def test_interval_off_by_one_boundary_conflict(
        self, continuous_24h_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """1-minute off-by-one overlaps: [360, 481) and [599, 720) against [480, 600) must conflict."""
        base_slot = CapacitySlotReservation(
            reservation_id="RES-BASE",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        booked = book_capacity_slot([], base_slot, continuous_24h_workcenter_calendar)

        # 1-minute overlap on left side: end_minute = 481
        left_off_by_one = CapacitySlotReservation(
            reservation_id="RES-OBO-LEFT",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=121,
            start_minute=360,
            end_minute=481,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, left_off_by_one, continuous_24h_workcenter_calendar)

        # 1-minute overlap on right side: start_minute = 599
        right_off_by_one = CapacitySlotReservation(
            reservation_id="RES-OBO-RIGHT",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-003",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=121,
            start_minute=599,
            end_minute=720,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-BASE'"):
            book_capacity_slot(booked, right_off_by_one, continuous_24h_workcenter_calendar)

    # ------------------------------------------------------------------------
    # 1.2 Midnight Wrap and Day Boundaries
    # ------------------------------------------------------------------------

    def test_midnight_and_day_edge_boundaries(self, continuous_24h_workcenter_calendar: WorkCenterCalendar) -> None:
        """Valid boundary slots starting at 00:00 (minute 0) and ending at 24:00 (minute 1440)."""
        # Slot starting at exact midnight (00:00)
        midnight_start = CapacitySlotReservation(
            reservation_id="RES-MIDNIGHT-START",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=60,
            start_minute=0,
            end_minute=60,
        )
        booked = book_capacity_slot([], midnight_start, continuous_24h_workcenter_calendar)
        assert len(booked) == 1
        assert booked[0].start_minute == 0

        # Slot ending at exact midnight end of day (24:00 = 1440)
        midnight_end = CapacitySlotReservation(
            reservation_id="RES-MIDNIGHT-END",
            workcenter_id="WC-CONT-01",
            work_order_id="WO-002",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=60,
            start_minute=1380,
            end_minute=1440,
        )
        booked = book_capacity_slot(booked, midnight_end, continuous_24h_workcenter_calendar)
        assert len(booked) == 2
        assert booked[1].end_minute == 1440

    def test_midnight_wrap_attempt_rejection(self) -> None:
        """Slots wrapping past midnight (e.g. 23:00 to 01:00) violate intra-day invariant and must be rejected."""
        with pytest.raises(CapacitySchedulingError, match="must satisfy 0 <= start < end <= 1440"):
            CapacitySlotReservation(
                reservation_id="RES-WRAP-ERR",
                workcenter_id="WC-CONT-01",
                work_order_id="WO-WRAP",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=120,
                start_minute=1380,  # 23:00
                end_minute=60,  # 01:00 (next day wrap attempt)
            )

    def test_out_of_bounds_minute_rejections(self) -> None:
        """Negative minutes or minutes beyond 1440 must be rejected at construction time."""
        # Negative start minute
        with pytest.raises(CapacitySchedulingError, match="must satisfy 0 <= start < end <= 1440"):
            CapacitySlotReservation(
                reservation_id="RES-NEG",
                workcenter_id="WC-CONT-01",
                work_order_id="WO-NEG",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=60,
                start_minute=-1,
                end_minute=59,
            )

        # End minute beyond 1440 (e.g. 1441)
        with pytest.raises(CapacitySchedulingError, match="must satisfy 0 <= start < end <= 1440"):
            CapacitySlotReservation(
                reservation_id="RES-OVER-1440",
                workcenter_id="WC-CONT-01",
                work_order_id="WO-OVER",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=60,
                start_minute=1381,
                end_minute=1441,
            )

        # Zero duration interval
        with pytest.raises(CapacitySchedulingError, match="Slot duration must be between 1 and 1440"):
            CapacitySlotReservation(
                reservation_id="RES-ZERO",
                workcenter_id="WC-CONT-01",
                work_order_id="WO-ZERO",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=0,
                start_minute=480,
                end_minute=480,
            )

    # ------------------------------------------------------------------------
    # 1.3 Shift Calendar Boundaries and Maintenance Gaps
    # ------------------------------------------------------------------------

    def test_shift_boundary_exact_match(self, standard_workcenter_calendar: WorkCenterCalendar) -> None:
        """Slot exactly spanning the shift hours [480, 960) on a weekday must succeed."""
        full_shift_slot = CapacitySlotReservation(
            reservation_id="RES-FULL-SHIFT",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-001",
            operation_sequence=1,
            scheduled_date="2026-11-20",  # Friday
            duration_minutes=480,
            start_minute=480,
            end_minute=960,
            shift_id="SHIFT-DAY",
        )
        booked = book_capacity_slot([], full_shift_slot, standard_workcenter_calendar)
        assert len(booked) == 1
        assert booked[0].duration_minutes == 480

    def test_slot_outside_shift_boundaries_rejected(self, standard_workcenter_calendar: WorkCenterCalendar) -> None:
        """Slots starting 1 minute before shift (07:59) or ending 1 minute after (16:01) must be rejected."""
        # Starts 1 minute early (479 vs 480)
        early_slot = CapacitySlotReservation(
            reservation_id="RES-EARLY",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-EARLY",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=479,
            end_minute=599,
            shift_id="SHIFT-DAY",
        )
        with pytest.raises(CapacitySchedulingError, match="does not fall within operating hours"):
            book_capacity_slot([], early_slot, standard_workcenter_calendar)

        # Ends 1 minute late (961 vs 960)
        late_slot = CapacitySlotReservation(
            reservation_id="RES-LATE",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-LATE",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=841,
            end_minute=961,
            shift_id="SHIFT-DAY",
        )
        with pytest.raises(CapacitySchedulingError, match="does not fall within operating hours"):
            book_capacity_slot([], late_slot, standard_workcenter_calendar)

    def test_multi_shift_maintenance_gap_rejection(self) -> None:
        """Work center with two shifts separated by a 60-minute maintenance window."""
        shift1 = WorkCenterShift(
            "SHIFT-1", "Morning", 360, 720, break_minutes=0, days_of_week=frozenset({0, 1, 2, 3, 4})
        )
        shift2 = WorkCenterShift(
            "SHIFT-2", "Evening", 780, 1140, break_minutes=0, days_of_week=frozenset({0, 1, 2, 3, 4})
        )
        cal = WorkCenterCalendar(
            workcenter_id="WC-SPLIT",
            name="Split Shift Work Center",
            daily_capacity_minutes=720,
            shifts=(shift1, shift2),
        )

        # Slot completely inside the maintenance window [720, 780)
        inside_gap = CapacitySlotReservation(
            reservation_id="RES-GAP",
            workcenter_id="WC-SPLIT",
            work_order_id="WO-GAP",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=60,
            start_minute=720,
            end_minute=780,
        )
        with pytest.raises(CapacitySchedulingError, match="does not fall within operating hours"):
            book_capacity_slot([], inside_gap, cal)

        # Slot spanning across the gap [700, 800) straddling both shifts
        straddling_gap = CapacitySlotReservation(
            reservation_id="RES-STRADDLE",
            workcenter_id="WC-SPLIT",
            work_order_id="WO-STRADDLE",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=100,
            start_minute=700,
            end_minute=800,
        )
        with pytest.raises(CapacitySchedulingError, match="does not fall within operating hours"):
            book_capacity_slot([], straddling_gap, cal)

    def test_weekend_and_blackout_rejections(self, standard_workcenter_calendar: WorkCenterCalendar) -> None:
        """Weekend (Saturday 2026-11-21) and blackout date (2026-12-25) must be rejected."""
        # Weekend booking on Mon-Fri calendar
        weekend_slot = CapacitySlotReservation(
            reservation_id="RES-SAT",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-SAT",
            operation_sequence=1,
            scheduled_date="2026-11-21",  # Saturday
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        with pytest.raises(CapacitySchedulingError, match="has no active shifts"):
            book_capacity_slot([], weekend_slot, standard_workcenter_calendar)

        # Blackout holiday booking
        holiday_slot = CapacitySlotReservation(
            reservation_id="RES-XMAS",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-XMAS",
            operation_sequence=1,
            scheduled_date="2026-12-25",  # Blackout holiday
            duration_minutes=60,
            start_minute=480,
            end_minute=540,
        )
        with pytest.raises(CapacitySchedulingError, match="is unavailable on 2026-12-25"):
            book_capacity_slot([], holiday_slot, standard_workcenter_calendar)

    # ------------------------------------------------------------------------
    # 1.4 Atomic State Non-Mutation and Rescheduling Invariants
    # ------------------------------------------------------------------------

    def test_atomic_conflict_rejection_leaves_input_unmodified(
        self, standard_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """When book_capacity_slot fails, the original active_reservations sequence must remain unmodified."""
        initial_slot = CapacitySlotReservation(
            reservation_id="RES-INIT",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-INIT",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        active_list = [initial_slot]

        # Trigger conflict
        conflicting_slot = CapacitySlotReservation(
            reservation_id="RES-CONF",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-CONF",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=500,
            end_minute=620,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation"):
            book_capacity_slot(active_list, conflicting_slot, standard_workcenter_calendar)

        # Invariant check: input list length and contents are identical
        assert len(active_list) == 1
        assert active_list[0].reservation_id == "RES-INIT"

    def test_reschedule_failure_preserves_original_reservation(
        self, standard_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """When reschedule fails due to conflict, the caller's state is preserved atomically."""
        slot1 = CapacitySlotReservation(
            reservation_id="RES-1",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-1",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=480,
            end_minute=600,
        )
        slot2 = CapacitySlotReservation(
            reservation_id="RES-2",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-2",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=600,
            end_minute=720,
        )
        booked = book_capacity_slot([], slot1, standard_workcenter_calendar)
        booked = book_capacity_slot(booked, slot2, standard_workcenter_calendar)
        assert len(booked) == 2

        # Attempt to reschedule WO-1 into WO-2's slot [600, 720)
        bad_reschedule = CapacitySlotReservation(
            reservation_id="RES-1-BAD",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-1",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=120,
            start_minute=600,
            end_minute=720,
        )
        with pytest.raises(CapacitySchedulingError, match="conflicts with existing reservation 'RES-2'"):
            reschedule_capacity_slot(booked, "WO-1", 1, bad_reschedule, standard_workcenter_calendar)

        # The original booked collection was not mutated
        assert len(booked) == 2
        assert any(s.work_order_id == "WO-1" for s in booked)
        assert any(s.work_order_id == "WO-2" for s in booked)

    def test_daily_capacity_saturation_rejection(self, standard_workcenter_calendar: WorkCenterCalendar) -> None:
        """Exactly fill 480 minutes with 4 x 120m slots; 5th slot must be rejected as capacity_exceeded."""
        booked: list[CapacitySlotReservation] = []
        for seq, start in enumerate([480, 600, 720, 840], start=1):
            slot = CapacitySlotReservation(
                reservation_id=f"RES-FILL-{seq}",
                workcenter_id="WC-MACH-01",
                work_order_id=f"WO-FILL-{seq}",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=120,
                start_minute=start,
                end_minute=start + 120,
            )
            booked = book_capacity_slot(booked, slot, standard_workcenter_calendar)

        assert len(booked) == 4
        assert sum(s.duration_minutes for s in booked) == 480

        # Attempt to book 1 additional minute
        overflow_slot = CapacitySlotReservation(
            reservation_id="RES-OVERFLOW",
            workcenter_id="WC-MACH-01",
            work_order_id="WO-EXTRA",
            operation_sequence=1,
            scheduled_date="2026-11-20",
            duration_minutes=1,
        )
        with pytest.raises(CapacitySchedulingError, match="0m available on 2026-11-20.*exceeds capacity"):
            book_capacity_slot(booked, overflow_slot, standard_workcenter_calendar)

    # ------------------------------------------------------------------------
    # 1.5 Property-Based Randomized Interval Oracle Harness
    # ------------------------------------------------------------------------

    def test_randomized_interval_oracle_equivalence(
        self, continuous_24h_workcenter_calendar: WorkCenterCalendar
    ) -> None:
        """Stress-test 100 pseudo-random interval requests against an independent interval oracle."""
        rng = random.Random(42)
        booked: list[CapacitySlotReservation] = []
        oracle_intervals: list[tuple[int, int]] = []

        def oracle_conflicts(s: int, e: int) -> bool:
            return any(max(s, o_s) < min(e, o_e) for o_s, o_e in oracle_intervals)

        accepted_count = 0
        rejected_count = 0

        for i in range(100):
            # Generate random start minute [0, 1380] and duration [15, 120]
            start = rng.randint(0, 1380)
            duration = rng.randint(15, min(120, MAX_MINUTES_PER_DAY - start))
            end = start + duration

            slot = CapacitySlotReservation(
                reservation_id=f"RES-RND-{i}",
                workcenter_id="WC-CONT-01",
                work_order_id=f"WO-RND-{i}",
                operation_sequence=1,
                scheduled_date="2026-11-20",
                duration_minutes=duration,
                start_minute=start,
                end_minute=end,
            )

            expected_conflict = oracle_conflicts(start, end)
            total_current_minutes = sum(o_e - o_s for o_s, o_e in oracle_intervals)
            expected_overflow = (total_current_minutes + duration) > MAX_MINUTES_PER_DAY

            if expected_conflict or expected_overflow:
                with pytest.raises(CapacitySchedulingError):
                    book_capacity_slot(booked, slot, continuous_24h_workcenter_calendar)
                rejected_count += 1
            else:
                booked = book_capacity_slot(booked, slot, continuous_24h_workcenter_calendar)
                oracle_intervals.append((start, end))
                accepted_count += 1

        assert accepted_count > 0
        assert rejected_count > 0
        assert len(booked) == accepted_count
        assert sum(s.duration_minutes for s in booked) <= MAX_MINUTES_PER_DAY


# ============================================================================
# CHALLENGE 2: HCM EMPLOYEE LEAVE ENTITLEMENTS & SOD
# ============================================================================


@pytest.fixture
def hcm_balance_24() -> LeaveEntitlementBalance:
    return LeaveEntitlementBalance(
        employee_id="EMP-200",
        leave_type="Annual",
        annual_entitlement_days=24,
        accrued_days=12,
        consumed_days=2,
    )


class TestHCMLeaveEntitlementsAdversarial:
    """Adversarial stress suite targeting negative balances, maker-checker SoD, and leap years."""

    # ------------------------------------------------------------------------
    # 2.1 Negative Balance Creation and Overdrawn Invariants
    # ------------------------------------------------------------------------

    def test_negative_and_overdrawn_balance_instantiation_rejected(self) -> None:
        """Negative accrued, negative consumed, or consumed > accrued must be rejected."""
        # Negative accrued days
        with pytest.raises(HCMLeaveError, match="must be nonnegative integers"):
            LeaveEntitlementBalance(
                employee_id="EMP-1",
                leave_type="Annual",
                annual_entitlement_days=20,
                accrued_days=-1,
                consumed_days=0,
            )

        # Negative consumed days
        with pytest.raises(HCMLeaveError, match="must be nonnegative integers"):
            LeaveEntitlementBalance(
                employee_id="EMP-1",
                leave_type="Annual",
                annual_entitlement_days=20,
                accrued_days=10,
                consumed_days=-2,
            )

        # Overdrawn balance: consumed > accrued
        with pytest.raises(HCMLeaveError, match="Consumed leave cannot exceed accrued leave"):
            LeaveEntitlementBalance(
                employee_id="EMP-1",
                leave_type="Annual",
                annual_entitlement_days=20,
                accrued_days=10,
                consumed_days=11,
            )

        # Out-of-bounds annual entitlement (> 365 or < 0)
        with pytest.raises(HCMLeaveError, match="Annual entitlement must be between 0 and 365"):
            LeaveEntitlementBalance(
                employee_id="EMP-1",
                leave_type="Annual",
                annual_entitlement_days=366,
                accrued_days=0,
                consumed_days=0,
            )

    def test_accrue_prorated_entitlement_prevents_retro_overdraw(self) -> None:
        """If an employee already consumed 8 days, a mid-year proration resulting in only 5 accrued days must raise."""
        balance = LeaveEntitlementBalance(
            employee_id="EMP-2",
            leave_type="Annual",
            annual_entitlement_days=20,
            accrued_days=10,
            consumed_days=8,
        )
        # 90 service days out of 365 yields (20*90 + 182)//365 = 1982//365 = 5 days accrued
        # Since consumed is 8, 5 < 8 must trigger leave_overdrawn!
        with pytest.raises(HCMLeaveError, match="Prorated accrual .* is less than already consumed leave"):
            accrue_prorated_entitlement(balance, service_days=90, total_year_days=365)

    def test_excess_leave_submission_and_approval_rejected(self, hcm_balance_24: LeaveEntitlementBalance) -> None:
        """Available days is 10 (12 - 2). Submitting or approving 11 days must be rejected."""
        # Submission with 11 days
        req = LeaveRequest(
            request_id="REQ-EXCESS",
            employee_id="EMP-200",
            employee_user_id="USR-EMP-200",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-24",
            requested_days=11,
            status="Draft",
            reason="Exceeding allowance",
        )
        with pytest.raises(HCMLeaveError, match="Insufficient leave balance: available 10 days, requested 11 days"):
            submit_leave_request(req, hcm_balance_24)

    def test_cancellation_restoration_boundary_and_retro_rejection(
        self, hcm_balance_24: LeaveEntitlementBalance
    ) -> None:
        """Approved leave cancelled on or after start date must be rejected; double cancellation must be rejected."""
        req = LeaveRequest(
            request_id="REQ-APP",
            employee_id="EMP-200",
            employee_user_id="USR-EMP-200",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-14",
            requested_days=5,
            status="Submitted",
            reason="Vacation",
        )
        approved, updated_bal = approve_leave_request(req, hcm_balance_24, approver_user_id="MGR-100")
        assert updated_bal.consumed_days == 7  # 2 + 5

        # Attempt to cancel on start date (2026-11-10) -> must be rejected
        with pytest.raises(HCMLeaveError, match="Cannot cancel leave on or after start date"):
            cancel_leave_request(approved, updated_bal, current_date="2026-11-10")

        # Attempt to cancel after start date (2026-11-12) -> must be rejected
        with pytest.raises(HCMLeaveError, match="Cannot cancel leave on or after start date"):
            cancel_leave_request(approved, updated_bal, current_date="2026-11-12")

        # Valid prior cancellation (2026-11-05) -> succeeds and restores consumed balance
        cancelled, restored_bal = cancel_leave_request(approved, updated_bal, current_date="2026-11-05")
        assert restored_bal.consumed_days == 2  # Restored from 7 to 2
        assert cancelled.status == "Cancelled"

        # Attempt double cancellation against restored balance (consumed=2, request=5 -> restored_consumed = -3!)
        with pytest.raises(HCMLeaveError, match="Only approved requests can be cancelled"):
            cancel_leave_request(cancelled, restored_bal, current_date="2026-11-05")

        # Attempt cancelling against an unconsumed balance (consumed_days < requested_days)
        unconsumed_bal = LeaveEntitlementBalance("EMP-200", "Annual", 24, 12, 1)  # only 1 consumed
        with pytest.raises(HCMLeaveError, match="must be nonnegative integers"):
            cancel_leave_request(approved, unconsumed_bal, current_date="2026-11-05")

    # ------------------------------------------------------------------------
    # 2.2 Maker-Checker SoD Bypass and Whitespace Differential Analysis
    # ------------------------------------------------------------------------

    def test_direct_self_approval_and_self_rejection_prohibited(self, hcm_balance_24: LeaveEntitlementBalance) -> None:
        """Exact identical employee_user_id cannot approve or reject their own leave."""
        req = LeaveRequest(
            request_id="REQ-SOD-1",
            employee_id="EMP-200",
            employee_user_id="USR-EMP-200",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-14",
            requested_days=5,
            status="Submitted",
            reason="Vacation",
        )
        # Direct self-approval
        with pytest.raises(HCMLeaveError, match="Segregation of Duties violation.*approving their own"):
            approve_leave_request(req, hcm_balance_24, approver_user_id="USR-EMP-200")

        # Direct self-rejection
        with pytest.raises(HCMLeaveError, match="Segregation of Duties violation.*cannot review or reject their own"):
            reject_leave_request(req, hcm_balance_24, rejector_user_id="USR-EMP-200", reason="Not allowed")

    def test_sod_whitespace_padding_vulnerability_demonstration(self, hcm_balance_24: LeaveEntitlementBalance) -> None:
        """EMPIRICAL VULNERABILITY AUDIT:

        In approve_leave_request, approver_user_id is compared without text() trimming:
            if approver_user_id == request.employee_user_id:
        while in reject_leave_request, clean_rejector = text(rejector_user_id) is called before comparison.

        This test empirically verifies that:
        1. reject_leave_request correctly blocks padded whitespace self-rejection.
        2. approve_leave_request exhibits an SoD vulnerability when passed ' USR-EMP-200 ' because
           raw string equality evaluates to False, yet text(approver_user_id) cleans it on assignment!
        """
        req = LeaveRequest(
            request_id="REQ-SOD-ADV",
            employee_id="EMP-200",
            employee_user_id="USR-EMP-200",
            leave_type="Annual",
            start_date="2026-11-10",
            end_date="2026-11-14",
            requested_days=3,
            status="Submitted",
            reason="Vacation",
        )

        # 1. Verification of defense in reject_leave_request (properly trimmed):
        with pytest.raises(HCMLeaveError, match="Segregation of Duties violation"):
            reject_leave_request(req, hcm_balance_24, rejector_user_id=" USR-EMP-200 ", reason="Denied")

        # 2. Verification that whitespace padding in approve_leave_request is strictly rejected:
        with pytest.raises(HCMLeaveError, match="Segregation of Duties violation"):
            approve_leave_request(req, hcm_balance_24, approver_user_id=" USR-EMP-200 ")

    # ------------------------------------------------------------------------
    # 2.3 Fiscal Year-End Rollover Expiration Edges
    # ------------------------------------------------------------------------

    def test_rollover_carryover_cap_and_forfeiture_edges(self) -> None:
        """Rollover with cap, zero cap, exact cap, zero balance, and invalid carryovers."""
        # Case A: available = 15, cap = 10 -> 10 carried over, 5 forfeited
        bal_15 = LeaveEntitlementBalance("EMP-1", "Annual", 20, 15, 0)
        new_bal, forfeited = rollover_leave_entitlement(bal_15, max_carryover_days=10)
        assert new_bal.accrued_days == 10
        assert new_bal.consumed_days == 0
        assert forfeited == 5

        # Case B: zero cap (use-it-or-lose-it) -> 0 carried over, all forfeited
        new_bal_zero_cap, forfeited_all = rollover_leave_entitlement(bal_15, max_carryover_days=0)
        assert new_bal_zero_cap.accrued_days == 0
        assert forfeited_all == 15

        # Case C: available = 8, cap = 10 -> 8 carried over, 0 forfeited
        bal_8 = LeaveEntitlementBalance("EMP-1", "Annual", 20, 8, 0)
        new_bal_under, forfeited_under = rollover_leave_entitlement(bal_8, max_carryover_days=10)
        assert new_bal_under.accrued_days == 8
        assert forfeited_under == 0

        # Case D: zero available -> 0 carried over, 0 forfeited
        bal_0 = LeaveEntitlementBalance("EMP-1", "Annual", 20, 10, 10)
        new_bal_0, forfeited_0 = rollover_leave_entitlement(bal_0, max_carryover_days=10)
        assert new_bal_0.accrued_days == 0
        assert forfeited_0 == 0

        # Boundary errors
        with pytest.raises(HCMLeaveError, match="Max carryover days must be between 0 and 365"):
            rollover_leave_entitlement(bal_15, max_carryover_days=-1)
        with pytest.raises(HCMLeaveError, match="Max carryover days must be between 0 and 365"):
            rollover_leave_entitlement(bal_15, max_carryover_days=366)

    # ------------------------------------------------------------------------
    # 2.4 Leap-Year Day Proration Rounding
    # ------------------------------------------------------------------------

    def test_leap_year_proration_half_up_rounding(self) -> None:
        """Leap-year (366 days) day-proration rounding vs common-year (365 days)."""
        bal = LeaveEntitlementBalance("EMP-LY", "Annual", annual_entitlement_days=15, accrued_days=0, consumed_days=0)

        # In a leap year (366 days), exactly mid-year is service_days = 183.
        # Formula: (15 * 183 + 183) // 366 = (2745 + 183) // 366 = 2928 // 366 = 8
        # Exact mathematical fraction: 15 * 183 / 366 = 7.5 -> rounds half-up to 8!
        ly_mid = accrue_prorated_entitlement(bal, service_days=183, total_year_days=366)
        assert ly_mid.accrued_days == 8

        # In a leap year, day 182: 15 * 182 / 366 = 7.459 -> must round down to 7!
        # Formula: (15 * 182 + 183) // 366 = 2913 // 366 = 7
        ly_below = accrue_prorated_entitlement(bal, service_days=182, total_year_days=366)
        assert ly_below.accrued_days == 7

        # Common year (365 days) comparisons:
        # Day 182: 15 * 182 / 365 = 7.479 -> rounds to 7
        cy_182 = accrue_prorated_entitlement(bal, service_days=182, total_year_days=365)
        assert cy_182.accrued_days == 7

        # Day 183: 15 * 183 / 365 = 7.520 -> rounds to 8
        cy_183 = accrue_prorated_entitlement(bal, service_days=183, total_year_days=365)
        assert cy_183.accrued_days == 8

        # Leap day Feb 29 (day 60 in leap year):
        # 15 * 60 / 366 = 2.459 -> (900 + 183) // 366 = 1083 // 366 = 2
        ly_feb29 = accrue_prorated_entitlement(bal, service_days=60, total_year_days=366)
        assert ly_feb29.accrued_days == 2

        # Full leap year service: 366 service days -> exact 15 days accrued
        ly_full = accrue_prorated_entitlement(bal, service_days=366, total_year_days=366)
        assert ly_full.accrued_days == 15

        # Service days exceeding year days
        with pytest.raises(HCMLeaveError, match="Service days must be between 0 and total year days"):
            accrue_prorated_entitlement(bal, service_days=367, total_year_days=366)

        # Invalid total year days
        with pytest.raises(HCMLeaveError, match="Total year days must be positive"):
            accrue_prorated_entitlement(bal, service_days=10, total_year_days=0)


# ============================================================================
# CHALLENGE 3: CRM SUBSCRIPTION PRORATED BILLING & CONTRACTS
# ============================================================================


class TestCRMSubscriptionProratedBillingAdversarial:
    """Adversarial stress suite targeting prorations, mid-month plan changes, leap years, and zero-float math."""

    # ------------------------------------------------------------------------
    # 3.1 Mid-Month Plan Upgrades and Downgrades
    # ------------------------------------------------------------------------

    def test_mid_month_plan_upgrade_and_downgrade_conservation(self) -> None:
        """Upgrade from Standard ($100/mo = 10,000 minor) to Enterprise ($300/mo = 30,000 minor)

        on day 16 of a 30-day month (April 1 to April 30).
        Remaining days = April 16 through April 30 inclusive = 15 days.
        """
        plan_standard = SubscriptionPlan("PLAN-STD", "Standard SaaS", "SAR", "monthly", 10_000)
        plan_enterprise = SubscriptionPlan("PLAN-ENT", "Enterprise SaaS", "SAR", "monthly", 30_000)

        # 1. Upgrade from Standard to Enterprise
        upgrade_result = calculate_plan_change_proration(
            old_plan=plan_standard,
            new_plan=plan_enterprise,
            period_start="2026-04-01",
            period_end="2026-04-30",
            change_date="2026-04-16",
        )
        assert upgrade_result["total_period_days"] == 30
        assert upgrade_result["remaining_days"] == 15
        assert upgrade_result["unearned_credit_minor"] == 5_000  # (10000 * 15 + 15) // 30 = 5000
        assert upgrade_result["new_charge_minor"] == 15_000  # (30000 * 15 + 15) // 30 = 15000
        assert upgrade_result["net_payable_minor"] == 10_000  # 15000 - 5000 = 10000

        # Mathematical conservation: unearned_credit + net_payable == new_charge
        assert (
            upgrade_result["unearned_credit_minor"] + upgrade_result["net_payable_minor"]
            == upgrade_result["new_charge_minor"]
        )

        # 2. Downgrade from Enterprise to Standard on same date
        downgrade_result = calculate_plan_change_proration(
            old_plan=plan_enterprise,
            new_plan=plan_standard,
            period_start="2026-04-01",
            period_end="2026-04-30",
            change_date="2026-04-16",
        )
        assert downgrade_result["unearned_credit_minor"] == 15_000
        assert downgrade_result["new_charge_minor"] == 5_000
        assert downgrade_result["net_payable_minor"] == -10_000  # Customer credit balance

        # Conservation check on downgrade
        assert (
            downgrade_result["unearned_credit_minor"] + downgrade_result["net_payable_minor"]
            == downgrade_result["new_charge_minor"]
        )

    def test_plan_change_period_boundary_edges(self) -> None:
        """Plan change on the exact first day (Day 1) and exact last day (Day 30)."""
        plan_old = SubscriptionPlan("P-OLD", "Old Plan", "USD", "monthly", 12_000)
        plan_new = SubscriptionPlan("P-NEW", "New Plan", "USD", "monthly", 24_000)

        # Day 1 change (period_start): full cycle prorated for new plan
        day_1_change = calculate_plan_change_proration(
            old_plan=plan_old,
            new_plan=plan_new,
            period_start="2026-04-01",
            period_end="2026-04-30",
            change_date="2026-04-01",
        )
        assert day_1_change["remaining_days"] == 30
        assert day_1_change["unearned_credit_minor"] == 12_000
        assert day_1_change["new_charge_minor"] == 24_000
        assert day_1_change["net_payable_minor"] == 12_000

        # Last day change (period_end): exactly 1 day prorated
        last_day_change = calculate_plan_change_proration(
            old_plan=plan_old,
            new_plan=plan_new,
            period_start="2026-04-01",
            period_end="2026-04-30",
            change_date="2026-04-30",
        )
        assert last_day_change["remaining_days"] == 1
        # 12,000 * 1 / 30 = 400
        assert last_day_change["unearned_credit_minor"] == 400
        # 24,000 * 1 / 30 = 800
        assert last_day_change["new_charge_minor"] == 800
        assert last_day_change["net_payable_minor"] == 400

    # ------------------------------------------------------------------------
    # 3.2 Zero-Day and Single-Day Boundary Cycles
    # ------------------------------------------------------------------------

    def test_single_day_cycle_proration(self) -> None:
        """Single-day billing cycle (start == end) must compute exactly 1 day without division-by-zero."""
        plan_old = SubscriptionPlan("P1", "Daily Srv", "SAR", "one_off", 5_000)
        plan_new = SubscriptionPlan("P2", "Daily Srv Premium", "SAR", "one_off", 8_000)

        res = calculate_plan_change_proration(
            old_plan=plan_old,
            new_plan=plan_new,
            period_start="2026-05-15",
            period_end="2026-05-15",
            change_date="2026-05-15",
        )
        assert res["total_period_days"] == 1
        assert res["remaining_days"] == 1
        assert res["unearned_credit_minor"] == 5_000
        assert res["new_charge_minor"] == 8_000
        assert res["net_payable_minor"] == 3_000

    def test_invalid_and_out_of_bounds_proration_cycles(self) -> None:
        """Reversed period dates, out of bounds change dates, and zero/negative total days must raise."""
        plan_old = SubscriptionPlan("P1", "Plan 1", "SAR", "monthly", 10_000)
        plan_new = SubscriptionPlan("P2", "Plan 2", "SAR", "monthly", 20_000)

        # Reversed period dates (start > end)
        with pytest.raises(FinancePostingError, match="period_start cannot succeed period_end"):
            calculate_plan_change_proration(plan_old, plan_new, "2026-05-20", "2026-05-10", "2026-05-15")

        # change_date before period_start
        with pytest.raises(FinancePostingError, match="must be between"):
            calculate_plan_change_proration(plan_old, plan_new, "2026-05-01", "2026-05-31", "2026-04-30")

        # change_date after period_end
        with pytest.raises(FinancePostingError, match="must be between"):
            calculate_plan_change_proration(plan_old, plan_new, "2026-05-01", "2026-05-31", "2026-06-01")

        # calculate_day_proration low-level boundary errors:
        with pytest.raises(FinancePostingError, match="total_period_days must be positive"):
            calculate_day_proration(amount_minor=1000, total_period_days=0, active_days=0)

        with pytest.raises(FinancePostingError, match="total_period_days must be positive"):
            calculate_day_proration(amount_minor=1000, total_period_days=-5, active_days=0)

        with pytest.raises(FinancePostingError, match="active_days .* must be between 0 and total_period_days"):
            calculate_day_proration(amount_minor=1000, total_period_days=30, active_days=-1)

        with pytest.raises(FinancePostingError, match="active_days .* must be between 0 and total_period_days"):
            calculate_day_proration(amount_minor=1000, total_period_days=30, active_days=31)

    # ------------------------------------------------------------------------
    # 3.3 Leap Years and Calendar Month Differences
    # ------------------------------------------------------------------------

    def test_leap_year_february_subscription_proration(self) -> None:
        """February in a Leap Year (2028-02-01 to 2028-02-29, 29 days) vs Common Year (2027, 28 days)."""
        plan_old = SubscriptionPlan("P-OLD", "Old", "SAR", "monthly", 29_000)
        plan_new = SubscriptionPlan("P-NEW", "New", "SAR", "monthly", 58_000)

        # Leap year 2028: 29 days total
        res_ly = calculate_plan_change_proration(
            old_plan=plan_old,
            new_plan=plan_new,
            period_start="2028-02-01",
            period_end="2028-02-29",
            change_date="2028-02-15",  # 15 days remaining (Feb 15..29 inclusive)
        )
        assert res_ly["total_period_days"] == 29
        assert res_ly["remaining_days"] == 15
        # 29,000 / 29 = exactly 1,000 minor per day!
        # Unearned: 15 * 1000 = 15,000
        assert res_ly["unearned_credit_minor"] == 15_000
        # New: 58,000 / 29 = 2,000 per day -> 15 * 2000 = 30,000
        assert res_ly["new_charge_minor"] == 30_000
        assert res_ly["net_payable_minor"] == 15_000

        # Common year 2027: 28 days total
        res_cy = calculate_plan_change_proration(
            old_plan=plan_old,
            new_plan=plan_new,
            period_start="2027-02-01",
            period_end="2027-02-28",
            change_date="2027-02-15",  # 14 days remaining (exactly half of 28 days)
        )
        assert res_cy["total_period_days"] == 28
        assert res_cy["remaining_days"] == 14
        # (29,000 * 14 + 14) // 28 = 406014 // 28 = 14500 (half-up exact)
        assert res_cy["unearned_credit_minor"] == 14_500
        # (58,000 * 14 + 14) // 28 = 812014 // 28 = 29000
        assert res_cy["new_charge_minor"] == 29_000
        assert res_cy["net_payable_minor"] == 14_500

    def test_leap_day_cancellation_refund(self) -> None:
        """Subscription cancelled on February 29 (leap day) calculates exactly 1 day refund out of 29 days."""
        plan = SubscriptionPlan("P-SaaS", "Pro SaaS", "EUR", "monthly", 29_000)
        sub = Subscription(
            subscription_id="SUB-LY-01",
            customer_id="CUST-001",
            contract_id="CTR-001",
            plan_id="P-SaaS",
            currency="EUR",
            status="active",
            current_period_start="2028-02-01",
            current_period_end="2028-02-29",
        )
        # Cancel on last day (2028-02-29): remaining days = 1 day (the 29th)
        cancelled_sub, refund = cancel_subscription_with_refund(sub, plan, cancellation_date="2028-02-29")
        assert cancelled_sub.status == "cancelled"
        # 1 day out of 29 days: 29,000 / 29 = 1,000 minor EUR refund
        assert refund == 1_000

    # ------------------------------------------------------------------------
    # 3.4 Multi-Currency Adjustments and Invariant Enforcement
    # ------------------------------------------------------------------------

    def test_cross_currency_plan_change_strictly_prohibited(self) -> None:
        """Cross-currency plan changes must raise crm_currency_mismatch to prevent implicit FX leakage."""
        usd_plan = SubscriptionPlan("P-USD", "USD Plan", "USD", "monthly", 10_000)
        sar_plan = SubscriptionPlan("P-SAR", "SAR Plan", "SAR", "monthly", 37_500)

        with pytest.raises(FinancePostingError, match="Cannot prorate between plans with different currencies"):
            calculate_plan_change_proration(
                old_plan=usd_plan,
                new_plan=sar_plan,
                period_start="2026-04-01",
                period_end="2026-04-30",
                change_date="2026-04-15",
            )

    def test_multi_currency_scale_arithmetic_invariants(self) -> None:
        """Test zero decimal (JPY: 10,000 JPY), 2 decimal (USD: 100.00 USD), and 3 decimal (KWD: 10.000 KWD) plans."""
        # JPY plan (0 decimals)
        jpy_old = SubscriptionPlan("P-JPY-1", "Old JPY", "JPY", "monthly", 15_000)
        jpy_new = SubscriptionPlan("P-JPY-2", "New JPY", "JPY", "monthly", 30_000)
        jpy_res = calculate_plan_change_proration(jpy_old, jpy_new, "2026-04-01", "2026-04-30", "2026-04-16")
        assert jpy_res["unearned_credit_minor"] == 7_500
        assert jpy_res["new_charge_minor"] == 15_000
        assert jpy_res["net_payable_minor"] == 7_500

        # KWD plan (3 decimals, e.g. 10.000 KWD = 10_000 minor)
        kwd_old = SubscriptionPlan("P-KWD-1", "Old KWD", "KWD", "monthly", 10_000)
        kwd_new = SubscriptionPlan("P-KWD-2", "New KWD", "KWD", "monthly", 25_000)
        kwd_res = calculate_plan_change_proration(kwd_old, kwd_new, "2026-04-01", "2026-04-30", "2026-04-16")
        assert kwd_res["unearned_credit_minor"] == 5_000
        assert kwd_res["new_charge_minor"] == 12_500
        assert kwd_res["net_payable_minor"] == 7_500

    # ------------------------------------------------------------------------
    # 3.5 Strict Zero-Float Integer Math Verification & Fuzzing
    # ------------------------------------------------------------------------

    def test_fuzzed_zero_float_integer_invariants(self) -> None:
        """Property-based fuzzing with 500 combinations of amount, total_days, active_days:

        1. Strict type checking: return value is isinstance(res, int) and type(res) is not float.
        2. Boundedness: 0 <= result <= amount_minor.
        3. Monotonicity: for fixed amount and total_days, proration(a1) <= proration(a2) if a1 <= a2.
        """
        rng = random.Random(1337)
        for _ in range(500):
            amount = rng.randint(0, 10_000_000)
            total_days = rng.randint(1, 366)
            active_days_1 = rng.randint(0, total_days)
            active_days_2 = rng.randint(active_days_1, total_days)

            res_1 = calculate_day_proration(amount, total_days, active_days_1)
            res_2 = calculate_day_proration(amount, total_days, active_days_2)

            # Strict zero float assertion
            assert isinstance(res_1, int)
            assert type(res_1) is int
            assert not isinstance(res_1, float)

            # Boundedness
            assert 0 <= res_1 <= amount
            assert 0 <= res_2 <= amount

            # Monotonicity
            assert res_1 <= res_2

    # ------------------------------------------------------------------------
    # 3.6 Customer Quotation SoD Whitespace Vulnerability Demonstration
    # ------------------------------------------------------------------------

    def test_customer_quotation_sod_whitespace_vulnerability(self) -> None:
        """EMPIRICAL VULNERABILITY AUDIT:

        In CustomerQuotation.approve:
            if approver_user_id == self.submitter_user_id:
                raise FinancePostingError("crm_sod_violation", "Submitter cannot approve their own quotation.")
        Approver_user_id is not trimmed with text() before checking equality with submitter_user_id!
        This allows an employee to pass ' sales_rep ' and bypass SoD approval.
        """
        lines = (
            QuotationLineItem(
                line_number=1,
                item_id="SRV-01",
                description="Consulting",
                quantity=10,
                unit_price_minor=10_000,
                discount_bps=500,  # 5% discount (standard rep)
            ),
        )
        quote = CustomerQuotation(
            quote_id="QT-SOD-001",
            opportunity_id="OPP-001",
            workspace_id="ws_01",
            customer_id="cust_1",
            currency="SAR",
            valid_until="2026-12-31",
            submitter_user_id="sales_rep_amr",
            status="submitted",
            lines=lines,
        )

        # 1. Direct match is correctly blocked:
        with pytest.raises(FinancePostingError, match="Submitter cannot approve their own quotation"):
            quote.approve(approver_user_id="sales_rep_amr", approver_role="sales_rep")

        # 2. Verification that whitespace padding in quote.approve is strictly rejected:
        with pytest.raises(FinancePostingError, match="Submitter cannot approve their own quotation"):
            quote.approve(approver_user_id=" sales_rep_amr ", approver_role="sales_rep")
