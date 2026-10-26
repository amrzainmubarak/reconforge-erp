"""FastAPI routes for Work Center Finite Capacity Planning, Calendars, and Slot Reservations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.enterprise_scope import enterprise_transaction
from reconforge.api.errors import APIError
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

router = APIRouter(prefix="/manufacturing/capacity", tags=["manufacturing-capacity"])
require_capacity_read = require_permission("manufacturing_execution.read")
require_capacity_manage = require_permission("manufacturing_execution.manage")
Read = Annotated[LocalUser, Depends(require_capacity_read)]
Manage = Annotated[LocalUser, Depends(require_capacity_manage)]


@contextmanager
def _get_repository(request: Request, *, permissions: frozenset[str], permission_mode: Literal["all", "any"] = "all") -> Iterator[tuple[Any, SqliteManufacturingCapacityRepository | PostgresManufacturingCapacityRepository]]:
    with enterprise_transaction(request, permissions=permissions, permission_mode=permission_mode) as business:
        if business is not None:
            connection = business.connection
            repository = PostgresManufacturingCapacityRepository(connection, business.scope.tenant_id)
            yield connection, repository
            return
        db_path = getattr(request.app.state, "db_path", None)
        if db_path is None:
            raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
        connection = sqlite3.connect(db_path)
        try:
            local_repository = SqliteManufacturingCapacityRepository(connection)
            yield connection, local_repository
        finally:
            connection.close()


class ShiftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shift_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    start_minute: int = Field(ge=0, le=1440)
    end_minute: int = Field(ge=0, le=1440)
    break_minutes: int = Field(default=0, ge=0, le=1440)
    days_of_week: list[int] = Field(default_factory=lambda: list(range(7)))


class CalendarPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workcenter_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    daily_capacity_minutes: int = Field(default=0, ge=0, le=1440)
    blackout_dates: list[str] = Field(default_factory=list)
    shifts: list[ShiftPayload] = Field(default_factory=list)
    fixed_asset_id: str | None = None


class SlotReservationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reservation_id: str = Field(min_length=1, max_length=64)
    workcenter_id: str = Field(min_length=1, max_length=64)
    work_order_id: str = Field(min_length=1, max_length=64)
    operation_sequence: int = Field(ge=1)
    scheduled_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    duration_minutes: int = Field(ge=1, le=1440)
    start_minute: int | None = Field(default=None, ge=0, le=1440)
    end_minute: int | None = Field(default=None, ge=0, le=1440)
    shift_id: str | None = None


class ReschedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    work_order_id: str = Field(min_length=1, max_length=64)
    operation_sequence: int = Field(ge=1)
    new_slot: SlotReservationPayload


@router.post("/calendars")
def save_calendar(
    request: Request,
    payload: CalendarPayload,
    user: Manage,
) -> dict[str, Any]:
    """Create or update work center calendar and shift definitions."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.manage'}), permission_mode="all") as ((conn, repo)):
        try:
            domain_shifts = tuple(
                WorkCenterShift(
                    shift_id=s.shift_id,
                    name=s.name,
                    start_minute=s.start_minute,
                    end_minute=s.end_minute,
                    break_minutes=s.break_minutes,
                    days_of_week=frozenset(s.days_of_week),
                )
                for s in payload.shifts
            )
            calendar = WorkCenterCalendar(
                workcenter_id=payload.workcenter_id,
                name=payload.name,
                daily_capacity_minutes=payload.daily_capacity_minutes,
                blackout_dates=frozenset(payload.blackout_dates),
                shifts=domain_shifts,
                fixed_asset_id=payload.fixed_asset_id,
            )
            workspace_id = getattr(request.state, "workspace_id", "default")
            if isinstance(repo, PostgresManufacturingCapacityRepository):
                repo.save_calendar(workspace_id=workspace_id, calendar=calendar, created_by=user.username)
            else:
                repo.save_calendar(workspace_id=workspace_id, calendar=calendar)
            return {
                "status": "saved",
                "workcenter_id": calendar.workcenter_id,
                "daily_capacity_minutes": calendar.daily_capacity_minutes,
                "shifts_count": len(calendar.shifts),
            }
        except CapacitySchedulingError as exc:
            raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc


@router.get("/calendars")
def list_calendars(
    request: Request,
    user: Read,
) -> dict[str, Any]:
    """List work center calendars in workspace."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.read'}), permission_mode="all") as ((conn, repo)):
        workspace_id = getattr(request.state, "workspace_id", "default")
        calendars = repo.list_calendars(workspace_id=workspace_id)
        return {
            "total_count": len(calendars),
            "calendars": [
                {
                    "workcenter_id": c.workcenter_id,
                    "name": c.name,
                    "daily_capacity_minutes": c.daily_capacity_minutes,
                    "blackout_dates": sorted(c.blackout_dates),
                    "shifts_count": len(c.shifts),
                    "fixed_asset_id": c.fixed_asset_id,
                }
                for c in calendars
            ],
        }


@router.get("/calendars/{workcenter_id}")
def get_calendar(
    request: Request,
    workcenter_id: str,
    user: Read,
) -> dict[str, Any]:
    """Get work center calendar by ID."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.read'}), permission_mode="all") as ((conn, repo)):
        workspace_id = getattr(request.state, "workspace_id", "default")
        cal = repo.get_calendar(workspace_id=workspace_id, workcenter_id=workcenter_id)
        if not cal:
            raise APIError(status_code=404, code="calendar_not_found", message=f"Calendar '{workcenter_id}' not found.")
        return {
            "workcenter_id": cal.workcenter_id,
            "name": cal.name,
            "daily_capacity_minutes": cal.daily_capacity_minutes,
            "blackout_dates": sorted(cal.blackout_dates),
            "shifts": [
                {
                    "shift_id": s.shift_id,
                    "name": s.name,
                    "start_minute": s.start_minute,
                    "end_minute": s.end_minute,
                    "break_minutes": s.break_minutes,
                    "days_of_week": sorted(s.days_of_week),
                    "net_working_minutes": s.net_working_minutes,
                }
                for s in cal.shifts
            ],
            "fixed_asset_id": cal.fixed_asset_id,
        }


@router.post("/reservations")
def book_reservation(
    request: Request,
    payload: SlotReservationPayload,
    user: Manage,
) -> dict[str, Any]:
    """Book a work center finite capacity slot atomically."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.manage'}), permission_mode="all") as ((conn, repo)):
        try:
            slot = CapacitySlotReservation(
                reservation_id=payload.reservation_id,
                workcenter_id=payload.workcenter_id,
                work_order_id=payload.work_order_id,
                operation_sequence=payload.operation_sequence,
                scheduled_date=payload.scheduled_date,
                duration_minutes=payload.duration_minutes,
                start_minute=payload.start_minute,
                end_minute=payload.end_minute,
                shift_id=payload.shift_id,
            )
            workspace_id = getattr(request.state, "workspace_id", "default")
            if isinstance(repo, PostgresManufacturingCapacityRepository):
                booked = repo.book_slot(workspace_id=workspace_id, slot=slot, created_by=user.username)
            else:
                booked = repo.book_slot(workspace_id=workspace_id, slot=slot)
            return {
                "status": "booked",
                "reservation_id": booked.reservation_id,
                "workcenter_id": booked.workcenter_id,
                "work_order_id": booked.work_order_id,
                "operation_sequence": booked.operation_sequence,
                "scheduled_date": booked.scheduled_date,
                "duration_minutes": booked.duration_minutes,
                "start_minute": booked.start_minute,
                "end_minute": booked.end_minute,
            }
        except CapacitySchedulingError as exc:
            raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc


@router.get("/reservations")
def list_reservations(
    request: Request,
    user: Read,
    workcenter_id: str | None = Query(default=None),
    scheduled_date: str | None = Query(default=None),
    active_only: bool = Query(default=True),
) -> dict[str, Any]:
    """List capacity slot reservations."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.read'}), permission_mode="all") as ((conn, repo)):
        workspace_id = getattr(request.state, "workspace_id", "default")
        slots = repo.list_reservations(
            workspace_id=workspace_id,
            workcenter_id=workcenter_id,
            scheduled_date=scheduled_date,
            active_only=active_only,
        )
        return {
            "total_count": len(slots),
            "reservations": [
                {
                    "reservation_id": s.reservation_id,
                    "workcenter_id": s.workcenter_id,
                    "work_order_id": s.work_order_id,
                    "operation_sequence": s.operation_sequence,
                    "scheduled_date": s.scheduled_date,
                    "duration_minutes": s.duration_minutes,
                    "start_minute": s.start_minute,
                    "end_minute": s.end_minute,
                    "shift_id": s.shift_id,
                }
                for s in slots
            ],
        }


@router.delete("/reservations/{work_order_id}/{operation_sequence}")
def release_reservation(
    request: Request,
    work_order_id: str,
    operation_sequence: int,
    user: Manage,
) -> dict[str, Any]:
    """Release an active capacity slot reservation."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.manage'}), permission_mode="all") as ((conn, repo)):
        try:
            workspace_id = getattr(request.state, "workspace_id", "default")
            if isinstance(repo, PostgresManufacturingCapacityRepository):
                repo.release_slot(
                    workspace_id=workspace_id,
                    work_order_id=work_order_id,
                    operation_sequence=operation_sequence,
                    actor=user.username,
                )
            else:
                repo.release_slot(
                    workspace_id=workspace_id,
                    work_order_id=work_order_id,
                    operation_sequence=operation_sequence,
                )
            return {
                "status": "released",
                "work_order_id": work_order_id,
                "operation_sequence": operation_sequence,
            }
        except CapacitySchedulingError as exc:
            raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc


@router.post("/reservations/reschedule")
def reschedule_reservation(
    request: Request,
    payload: ReschedulePayload,
    user: Manage,
) -> dict[str, Any]:
    """Reschedule a slot reservation atomically."""
    with _get_repository(request, permissions=frozenset({'manufacturing_execution.manage'}), permission_mode="all") as ((conn, repo)):
        try:
            new_slot = CapacitySlotReservation(
                reservation_id=payload.new_slot.reservation_id,
                workcenter_id=payload.new_slot.workcenter_id,
                work_order_id=payload.new_slot.work_order_id,
                operation_sequence=payload.new_slot.operation_sequence,
                scheduled_date=payload.new_slot.scheduled_date,
                duration_minutes=payload.new_slot.duration_minutes,
                start_minute=payload.new_slot.start_minute,
                end_minute=payload.new_slot.end_minute,
                shift_id=payload.new_slot.shift_id,
            )
            workspace_id = getattr(request.state, "workspace_id", "default")
            if isinstance(repo, PostgresManufacturingCapacityRepository):
                rescheduled = repo.reschedule_slot(
                    workspace_id=workspace_id,
                    work_order_id=payload.work_order_id,
                    operation_sequence=payload.operation_sequence,
                    new_slot=new_slot,
                    actor=user.username,
                )
            else:
                rescheduled = repo.reschedule_slot(
                    workspace_id=workspace_id,
                    work_order_id=payload.work_order_id,
                    operation_sequence=payload.operation_sequence,
                    new_slot=new_slot,
                )
            return {
                "status": "rescheduled",
                "reservation_id": rescheduled.reservation_id,
                "workcenter_id": rescheduled.workcenter_id,
                "work_order_id": rescheduled.work_order_id,
                "operation_sequence": rescheduled.operation_sequence,
                "scheduled_date": rescheduled.scheduled_date,
                "duration_minutes": rescheduled.duration_minutes,
                "start_minute": rescheduled.start_minute,
                "end_minute": rescheduled.end_minute,
            }
        except CapacitySchedulingError as exc:
            raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
