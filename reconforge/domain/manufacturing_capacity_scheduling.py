"""Deterministic Work Center capacity planning and atomic slot reservation.

Enforces finite capacity constraints, holiday/maintenance exclusions, and atomic
rescheduling without double-booking or capacity over-allocation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from reconforge.domain.finance_posting import FinancePostingError, text

MAX_MINUTES_PER_DAY = 1440  # 24 hours in minutes


class CapacitySchedulingError(FinancePostingError):
    """Raised when a capacity booking violates work center calendar or capacity limits."""


@dataclass(frozen=True)
class WorkCenterShift:
    """Operating shift window for a work center."""

    shift_id: str
    name: str
    start_minute: int  # Minutes from midnight, e.g. 480 = 08:00
    end_minute: int    # Minutes from midnight, e.g. 1020 = 17:00
    break_minutes: int = 0
    days_of_week: frozenset[int] = frozenset(range(7))  # 0=Monday .. 6=Sunday

    def __post_init__(self) -> None:
        text(self.shift_id, "shift_id", maximum=64)
        text(self.name, "name", maximum=160)
        if not (0 <= self.start_minute < self.end_minute <= MAX_MINUTES_PER_DAY):
            raise CapacitySchedulingError(
                "shift_window_invalid",
                f"Shift window must satisfy 0 <= start_minute ({self.start_minute}) < end_minute ({self.end_minute}) <= {MAX_MINUTES_PER_DAY}."
            )
        duration = self.end_minute - self.start_minute
        if not (0 <= self.break_minutes < duration):
            raise CapacitySchedulingError(
                "shift_break_invalid",
                f"Break minutes ({self.break_minutes}) must be between 0 and duration ({duration})."
            )
        for dow in self.days_of_week:
            if not (0 <= dow <= 6):
                raise CapacitySchedulingError(
                    "shift_day_invalid",
                    f"Day of week {dow} must be between 0 (Monday) and 6 (Sunday)."
                )

    @property
    def net_working_minutes(self) -> int:
        return (self.end_minute - self.start_minute) - self.break_minutes


@dataclass(frozen=True)
class WorkCenterCalendar:
    workcenter_id: str
    name: str
    daily_capacity_minutes: int = 0
    blackout_dates: frozenset[str] = frozenset()  # Dates (YYYY-MM-DD) unavailable for production
    shifts: tuple[WorkCenterShift, ...] = ()
    fixed_asset_id: str | None = None

    def __post_init__(self) -> None:
        text(self.workcenter_id, "workcenter_id")
        text(self.name, "name", maximum=160)
        if self.fixed_asset_id is not None:
            text(self.fixed_asset_id, "fixed_asset_id", maximum=64)
        if self.shifts and self.daily_capacity_minutes == 0:
            total_shift_minutes = sum(s.net_working_minutes for s in self.shifts)
            object.__setattr__(self, "daily_capacity_minutes", min(total_shift_minutes, MAX_MINUTES_PER_DAY))
        if not 1 <= self.daily_capacity_minutes <= MAX_MINUTES_PER_DAY:
            raise CapacitySchedulingError(
                "capacity_invalid",
                f"Daily capacity must be between 1 and {MAX_MINUTES_PER_DAY} minutes."
            )
        for d in self.blackout_dates:
            try:
                if date.fromisoformat(d).isoformat() != d:
                    raise ValueError
            except (TypeError, ValueError):
                raise CapacitySchedulingError(
                    "capacity_date_invalid", "Blackout dates require canonical YYYY-MM-DD values.",
                ) from None


@dataclass(frozen=True)
class CapacitySlotReservation:
    reservation_id: str
    workcenter_id: str
    work_order_id: str
    operation_sequence: int
    scheduled_date: str
    duration_minutes: int
    start_minute: int | None = None
    end_minute: int | None = None
    shift_id: str | None = None

    def __post_init__(self) -> None:
        text(self.reservation_id, "reservation_id")
        text(self.workcenter_id, "workcenter_id")
        text(self.work_order_id, "work_order_id")
        if self.operation_sequence < 1:
            raise CapacitySchedulingError("capacity_sequence_invalid", "Operation sequence must be >= 1.")
        try:
            if date.fromisoformat(self.scheduled_date).isoformat() != self.scheduled_date:
                raise ValueError
        except (TypeError, ValueError):
            raise CapacitySchedulingError(
                "capacity_date_invalid", "Scheduled dates require canonical YYYY-MM-DD values.",
            ) from None
        if not 1 <= self.duration_minutes <= MAX_MINUTES_PER_DAY:
            raise CapacitySchedulingError(
                "capacity_duration_invalid",
                f"Slot duration must be between 1 and {MAX_MINUTES_PER_DAY} minutes."
            )
        if self.start_minute is not None or self.end_minute is not None:
            if self.start_minute is None or self.end_minute is None:
                raise CapacitySchedulingError(
                    "capacity_interval_incomplete",
                    "Both start_minute and end_minute must be provided together."
                )
            if not (0 <= self.start_minute < self.end_minute <= MAX_MINUTES_PER_DAY):
                raise CapacitySchedulingError(
                    "capacity_interval_invalid",
                    f"Interval [start_minute={self.start_minute}, end_minute={self.end_minute}] must satisfy 0 <= start < end <= {MAX_MINUTES_PER_DAY}."
                )
            if (self.end_minute - self.start_minute) != self.duration_minutes:
                raise CapacitySchedulingError(
                    "capacity_duration_mismatch",
                    f"Slot duration ({self.duration_minutes}m) must equal end_minute - start_minute ({self.end_minute - self.start_minute}m)."
                )
        if self.shift_id is not None:
            text(self.shift_id, "shift_id", maximum=64)


def book_capacity_slot(
    active_reservations: Sequence[CapacitySlotReservation],
    new_slot: CapacitySlotReservation,
    calendar: WorkCenterCalendar,
) -> list[CapacitySlotReservation]:
    """Atomically books a work center slot, refusing overbooking, interval conflicts, and blackout dates."""
    if new_slot.workcenter_id != calendar.workcenter_id:
        raise CapacitySchedulingError(
            "capacity_mismatch",
            f"Slot work center '{new_slot.workcenter_id}' does not match calendar '{calendar.workcenter_id}'."
        )

    if new_slot.scheduled_date in calendar.blackout_dates:
        raise CapacitySchedulingError(
            "capacity_blackout",
            f"Work center '{calendar.workcenter_id}' is unavailable on {new_slot.scheduled_date} (maintenance/holiday)."
        )

    # Check for duplicate operation booking
    for slot in active_reservations:
        if (
            slot.work_order_id == new_slot.work_order_id
            and slot.operation_sequence == new_slot.operation_sequence
        ):
            raise CapacitySchedulingError(
                "capacity_duplicate",
                f"Work order '{new_slot.work_order_id}' sequence {new_slot.operation_sequence} already has a booked slot."
            )

    # Shift calendar enforcement if calendar defines shifts
    matching_shift: WorkCenterShift | None = None
    if calendar.shifts:
        target_date = date.fromisoformat(new_slot.scheduled_date)
        dow = target_date.weekday()
        day_shifts = [s for s in calendar.shifts if dow in s.days_of_week]
        if not day_shifts:
            raise CapacitySchedulingError(
                "capacity_shift_unavailable",
                f"Work center '{calendar.workcenter_id}' has no active shifts on {new_slot.scheduled_date} (day-of-week {dow})."
            )
        if new_slot.shift_id:
            matching_shift = next((s for s in day_shifts if s.shift_id == new_slot.shift_id), None)
            if not matching_shift:
                raise CapacitySchedulingError(
                    "capacity_shift_unavailable",
                    f"Shift '{new_slot.shift_id}' is not active on {new_slot.scheduled_date} for work center '{calendar.workcenter_id}'."
                )
        if new_slot.start_minute is not None and new_slot.end_minute is not None:
            shifts_to_test = [matching_shift] if (new_slot.shift_id and matching_shift) else day_shifts
            in_shift = any(
                s.start_minute <= new_slot.start_minute and new_slot.end_minute <= s.end_minute
                for s in shifts_to_test
            )
            if not in_shift:
                raise CapacitySchedulingError(
                    "capacity_shift_out_of_bounds",
                    f"Slot [{new_slot.start_minute}, {new_slot.end_minute}] does not fall within operating hours of active shift(s) on {new_slot.scheduled_date}."
                )

    # Finite interval overlap conflict check on the same work center and date
    if new_slot.start_minute is not None and new_slot.end_minute is not None:
        for slot in active_reservations:
            if (
                slot.workcenter_id == new_slot.workcenter_id
                and slot.scheduled_date == new_slot.scheduled_date
                and slot.start_minute is not None
                and slot.end_minute is not None
                and max(new_slot.start_minute, slot.start_minute) < min(new_slot.end_minute, slot.end_minute)
            ):
                raise CapacitySchedulingError(
                    "capacity_conflict",
                    f"Work center '{calendar.workcenter_id}' slot [{new_slot.start_minute}, {new_slot.end_minute}] "
                    f"conflicts with existing reservation '{slot.reservation_id}' [{slot.start_minute}, {slot.end_minute}] "
                    f"on {new_slot.scheduled_date}."
                )

    # Sum consumed minutes on the target date
    consumed_minutes = sum(
        slot.duration_minutes
        for slot in active_reservations
        if slot.workcenter_id == calendar.workcenter_id and slot.scheduled_date == new_slot.scheduled_date
    )

    remaining_capacity = calendar.daily_capacity_minutes - consumed_minutes
    if new_slot.duration_minutes > remaining_capacity:
        raise CapacitySchedulingError(
            "capacity_exceeded",
            f"Work center '{calendar.workcenter_id}' has {remaining_capacity}m available on {new_slot.scheduled_date}; "
            f"requested {new_slot.duration_minutes}m exceeds capacity."
        )

    result = list(active_reservations)
    result.append(new_slot)
    return sorted(
        result,
        key=lambda s: (
            s.scheduled_date,
            s.workcenter_id,
            s.start_minute if s.start_minute is not None else -1,
            s.work_order_id,
            s.operation_sequence,
        ),
    )


def release_capacity_slot(
    active_reservations: Sequence[CapacitySlotReservation],
    work_order_id: str,
    operation_sequence: int,
) -> list[CapacitySlotReservation]:
    """Atomically releases a previously booked capacity slot."""
    released = [
        slot
        for slot in active_reservations
        if not (slot.work_order_id == work_order_id and slot.operation_sequence == operation_sequence)
    ]
    if len(released) == len(active_reservations):
        raise CapacitySchedulingError(
            "capacity_not_found",
            f"No active slot found for work order '{work_order_id}' sequence {operation_sequence}."
        )
    return released


def reschedule_capacity_slot(
    active_reservations: Sequence[CapacitySlotReservation],
    work_order_id: str,
    operation_sequence: int,
    new_slot: CapacitySlotReservation,
    calendar: WorkCenterCalendar,
) -> list[CapacitySlotReservation]:
    """Atomically reschedules a slot by releasing the existing reservation before booking the new one."""
    released = release_capacity_slot(active_reservations, work_order_id, operation_sequence)
    return book_capacity_slot(released, new_slot, calendar)


__all__ = [
    "MAX_MINUTES_PER_DAY",
    "CapacitySchedulingError",
    "CapacitySlotReservation",
    "WorkCenterCalendar",
    "WorkCenterShift",
    "book_capacity_slot",
    "release_capacity_slot",
    "reschedule_capacity_slot",
]
