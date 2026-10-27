"""Canonical calendar identities must agree before writes and blackout matching."""

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reconforge.api.errors import APIError, api_error_handler
from reconforge.api.routes.manufacturing_capacity import require_capacity_manage, router
from reconforge.auth.models import LocalUser
from reconforge.domain.manufacturing_capacity_scheduling import (
    CapacitySchedulingError,
    CapacitySlotReservation,
    WorkCenterCalendar,
    book_capacity_slot,
)


@pytest.mark.parametrize("value", ["20261026", "2026-W44-1", "2026-02-30", "SECRET-DATE-SENTINEL"])
@pytest.mark.parametrize("field", ["blackout", "scheduled"])
def test_capacity_domain_rejects_noncanonical_dates_safely(value: str, field: str) -> None:
    with pytest.raises(CapacitySchedulingError) as failure:
        if field == "blackout":
            WorkCenterCalendar("center", "Synthetic calendar", 60, frozenset({value}))
        else:
            CapacitySlotReservation("slot", "center", "order", 1, value, 30)
    assert failure.value.code == "capacity_date_invalid"
    assert "SECRET-DATE-SENTINEL" not in str(failure.value)


def test_canonical_blackout_and_booking_share_exact_date_identity() -> None:
    calendar = WorkCenterCalendar("center", "Synthetic calendar", 60, frozenset({"2026-10-26"}))
    slot = CapacitySlotReservation("slot", "center", "order", 1, "2026-10-26", 30)
    with pytest.raises(CapacitySchedulingError) as failure:
        book_capacity_slot([], slot, calendar)
    assert failure.value.code == "capacity_blackout"
    permitted = CapacitySlotReservation("permitted", "center", "order", 1, "2026-10-27", 30)
    assert book_capacity_slot([], permitted, calendar) == [permitted]


@pytest.mark.parametrize("value", ["20261026", "2026-W44-1"])
def test_calendar_api_rejects_noncanonical_dates_before_persistence(tmp_path: Path, value: str) -> None:
    path = tmp_path / "capacity.sqlite"
    app = FastAPI()
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.include_router(router, prefix="/api/v1")
    app.state.db_path, app.state.server_mode = str(path), False
    user = LocalUser(id="synthetic-manager", username="synthetic-manager", display_name="Synthetic manager")
    app.dependency_overrides[require_capacity_manage] = lambda: user
    with TestClient(app) as client:
        response = client.post("/api/v1/manufacturing/capacity/calendars", json={
            "workcenter_id": "center", "name": "Synthetic calendar", "daily_capacity_minutes": 60,
            "blackout_dates": [value],
        })
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "capacity_date_invalid"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM workcenter_calendars").fetchall() == []
        assert connection.execute("SELECT * FROM workcenter_shifts").fetchall() == []
