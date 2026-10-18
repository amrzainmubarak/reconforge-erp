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
class WorkCenterCalendar:
    workcenter_id: str
    name: str
    daily_capacity_minutes: int
    blackout_dates: frozenset[str]  # Dates (YYYY-MM-DD) unavailable for production

    def __post_init__(self) -> None:
        text(self.workcenter_id, "workcenter_id")
        text(self.name, "name", maximum=160)
        if not 1 <= self.daily_capacity_minutes <= MAX_MINUTES_PER_DAY:
            raise CapacitySchedulingError(
                "capacity_invalid",
                f"Daily capacity must be between 1 and {MAX_MINUTES_PER_DAY} minutes."
            )
        for d in self.blackout_dates:
            try:
                date.fromisoformat(d)
            except ValueError as exc:
                raise CapacitySchedulingError("capacity_date_invalid", f"Invalid blackout date format: {d}") from exc


@dataclass(frozen=True)
class CapacitySlotReservation:
    reservation_id: str
    workcenter_id: str
    work_order_id: str
    operation_sequence: int
    scheduled_date: str
    duration_minutes: int

    def __post_init__(self) -> None:
        text(self.reservation_id, "reservation_id")
        text(self.workcenter_id, "workcenter_id")
        text(self.work_order_id, "work_order_id")
        if self.operation_sequence < 1:
            raise CapacitySchedulingError("capacity_sequence_invalid", "Operation sequence must be >= 1.")
        try:
            date.fromisoformat(self.scheduled_date)
        except ValueError as exc:
            raise CapacitySchedulingError("capacity_date_invalid", f"Invalid scheduled date: {self.scheduled_date}") from exc
        if not 1 <= self.duration_minutes <= MAX_MINUTES_PER_DAY:
            raise CapacitySchedulingError(
                "capacity_duration_invalid",
                f"Slot duration must be between 1 and {MAX_MINUTES_PER_DAY} minutes."
            )


def book_capacity_slot(
    active_reservations: Sequence[CapacitySlotReservation],
    new_slot: CapacitySlotReservation,
    calendar: WorkCenterCalendar,
) -> list[CapacitySlotReservation]:
    """Atomically books a work center slot, refusing overbooking and blackout dates."""
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
    return sorted(result, key=lambda s: (s.scheduled_date, s.workcenter_id, s.work_order_id, s.operation_sequence))


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
