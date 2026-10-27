"""Capacity rescheduling validates and persists with an already active transaction."""

import sqlite3

import pytest

from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
)
from reconforge.infrastructure.sqlite_manufacturing_capacity import (
    SqliteManufacturingCapacityRepository,
)


@pytest.mark.parametrize("transaction_open", [False, True])
@pytest.mark.parametrize("duration", [30, 61])
def test_reschedule_does_not_skip_existing_transaction(
    transaction_open: bool, duration: int,
) -> None:
    with sqlite3.connect(":memory:") as connection:
        repository = SqliteManufacturingCapacityRepository(connection)
        repository.save_calendar(
            workspace_id="workspace", calendar=WorkCenterCalendar("center", "Calendar", 60),
        )
        old = CapacitySlotReservation("old", "center", "order", 1, "2026-10-26", 30)
        replacement = CapacitySlotReservation(
            "replacement", "center", "order", 1, "2026-10-27", duration,
        )
        repository.book_slot(workspace_id="workspace", slot=old)
        if transaction_open:
            connection.execute("BEGIN IMMEDIATE")

        if duration > 60:
            with pytest.raises(CapacitySchedulingError):
                repository.reschedule_slot(
                    workspace_id="workspace", work_order_id="order", operation_sequence=1,
                    new_slot=replacement,
                )
            assert repository.list_reservations(workspace_id="workspace") == [old]
            assert connection.execute(
                "SELECT reservation_id, status FROM capacity_slot_reservations",
            ).fetchall() == [("old", "BOOKED")]
        else:
            assert repository.reschedule_slot(
                workspace_id="workspace", work_order_id="order", operation_sequence=1,
                new_slot=replacement,
            ) == replacement
            assert repository.list_reservations(workspace_id="workspace") == [replacement]
            assert connection.execute(
                "SELECT reservation_id, status FROM capacity_slot_reservations ORDER BY reservation_id",
            ).fetchall() == [("old", "RELEASED"), ("replacement", "BOOKED")]
