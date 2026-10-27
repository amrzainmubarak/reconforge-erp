"""Equipment Maintenance Integration and Work Center Capacity Blackout Booking.

Links production work centers directly to the Fixed Asset register (fixed_asset_id),
schedules preventive/corrective maintenance orders, automatically reserves
capacity blackout windows on work center calendars, and accumulates integer maintenance costs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySlotReservation,
    WorkCenterCalendar,
    book_capacity_slot,
)
from reconforge.domain.manufacturing_execution import exact_integer, fail
from reconforge.domain.models import utc_now_text

MaintenanceType = Literal["preventive", "corrective", "calibration", "emergency"]
MaintenanceStatus = Literal["draft", "scheduled", "in_progress", "completed", "cancelled"]


class MaintenanceError(FinancePostingError):
    """Raised when equipment maintenance invariants or schedule constraints are violated."""


@dataclass(frozen=True)
class MaintenanceSparePart:
    """A replacement component or consumable used in a maintenance work order."""

    item_id: str
    part_name: str
    quantity_required: int
    unit_cost_minor: int  # In integer minor currency units (e.g. cents)

    def __post_init__(self) -> None:
        text(self.item_id, "item_id", maximum=64)
        text(self.part_name, "part_name", maximum=128)
        exact_integer(self.quantity_required, positive=True)
        exact_integer(self.unit_cost_minor)

    @property
    def total_cost_minor(self) -> int:
        return self.quantity_required * self.unit_cost_minor


@dataclass(frozen=True)
class MaintenanceWorkOrder:
    """Work order for equipment maintenance linked to a fixed asset."""

    maintenance_order_id: str
    workcenter_id: str
    fixed_asset_id: str
    maintenance_type: MaintenanceType
    description: str
    scheduled_date: str  # YYYY-MM-DD
    start_minute: int  # Minutes from midnight (e.g. 480 = 08:00)
    end_minute: int    # Minutes from midnight (e.g. 720 = 12:00)
    spare_parts: tuple[MaintenanceSparePart, ...] = ()
    labor_technician_id: str = "TECH_UNASSIGNED"
    labor_rate_hourly_minor: int = 0
    actual_labor_minutes: int = 0
    status: MaintenanceStatus = "draft"
    notes: str = ""
    created_at: str = ""
    completed_at: str | None = None

    def __post_init__(self) -> None:
        text(self.maintenance_order_id, "maintenance_order_id", maximum=64)
        text(self.workcenter_id, "workcenter_id", maximum=64)
        text(self.fixed_asset_id, "fixed_asset_id", maximum=64)
        text(self.description, "description", maximum=255)
        text(self.labor_technician_id, "labor_technician_id", maximum=64)
        try:
            date.fromisoformat(self.scheduled_date)
        except ValueError as exc:
            raise MaintenanceError("maintenance_date_invalid", f"Invalid scheduled date: {self.scheduled_date}") from exc
        if not (0 <= self.start_minute < self.end_minute <= 1440):
            fail(
                f"Maintenance window [{self.start_minute}, {self.end_minute}] must satisfy 0 <= start < end <= 1440.",
                "maintenance_window_invalid",
            )
        exact_integer(self.labor_rate_hourly_minor)
        exact_integer(self.actual_labor_minutes)
        if not self.created_at:
            object.__setattr__(self, "created_at", utc_now_text())

    @property
    def duration_minutes(self) -> int:
        return self.end_minute - self.start_minute

    @property
    def spare_parts_cost_minor(self) -> int:
        return sum(part.total_cost_minor for part in self.spare_parts)

    @property
    def labor_cost_minor(self) -> int:
        return (self.actual_labor_minutes * self.labor_rate_hourly_minor + 30) // 60

    @property
    def total_maintenance_cost_minor(self) -> int:
        return self.spare_parts_cost_minor + self.labor_cost_minor

    def schedule_and_book_blackout(
        self,
        *,
        calendar: WorkCenterCalendar,
        existing_reservations: list[CapacitySlotReservation] | None = None,
        as_full_day_blackout: bool = False,
    ) -> tuple[MaintenanceWorkOrder, WorkCenterCalendar, CapacitySlotReservation | None]:
        """Validates equipment link and auto-books maintenance blackout on the calendar."""
        if self.status != "draft":
            raise MaintenanceError(
                "maintenance_not_draft",
                f"Cannot schedule maintenance order '{self.maintenance_order_id}' in status '{self.status}'.",
            )
        if calendar.workcenter_id != self.workcenter_id:
            raise MaintenanceError(
                "maintenance_workcenter_mismatch",
                f"Work order work center '{self.workcenter_id}' does not match calendar '{calendar.workcenter_id}'.",
            )
        if calendar.fixed_asset_id is not None and calendar.fixed_asset_id != self.fixed_asset_id:
            raise MaintenanceError(
                "maintenance_asset_mismatch",
                f"Calendar fixed asset '{calendar.fixed_asset_id}' does not match maintenance asset '{self.fixed_asset_id}'.",
            )

        updated_cal = calendar
        reservation: CapacitySlotReservation | None = None

        if as_full_day_blackout:
            updated_blackouts = calendar.blackout_dates | {self.scheduled_date}
            updated_cal = replace(calendar, blackout_dates=updated_blackouts)
        else:
            slot = CapacitySlotReservation(
                reservation_id=f"RES-MAINT-{self.maintenance_order_id}",
                workcenter_id=self.workcenter_id,
                work_order_id=self.maintenance_order_id,
                operation_sequence=1,
                scheduled_date=self.scheduled_date,
                duration_minutes=self.duration_minutes,
                start_minute=self.start_minute,
                end_minute=self.end_minute,
            )
            # Validate interval conflict against existing reservations
            active = existing_reservations or []
            book_capacity_slot(active, slot, calendar)
            reservation = slot

        updated_order = replace(self, status="scheduled")
        return updated_order, updated_cal, reservation

    def start_maintenance(self) -> MaintenanceWorkOrder:
        """Transitions status to in_progress."""
        if self.status != "scheduled":
            raise MaintenanceError(
                "maintenance_invalid_status",
                f"Cannot start maintenance order in status '{self.status}'.",
            )
        return replace(self, status="in_progress")

    def complete_maintenance(self, *, actual_labor_minutes: int, notes: str = "") -> MaintenanceWorkOrder:
        """Completes maintenance work order and finalizes actual labor duration."""
        if self.status not in ("scheduled", "in_progress"):
            raise MaintenanceError(
                "maintenance_invalid_status",
                f"Cannot complete maintenance order in status '{self.status}'.",
            )
        exact_integer(actual_labor_minutes, positive=True)
        return replace(
            self,
            status="completed",
            actual_labor_minutes=actual_labor_minutes,
            notes=notes,
            completed_at=utc_now_text(),
        )


__all__ = [
    "MaintenanceError",
    "MaintenanceSparePart",
    "MaintenanceStatus",
    "MaintenanceType",
    "MaintenanceWorkOrder",
]
