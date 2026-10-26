"""Malformed stored restrictions must never become permissive empty calendars."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.domain.manufacturing_capacity_scheduling import CapacitySchedulingError
from reconforge.infrastructure.postgres_manufacturing_capacity import PostgresManufacturingCapacityRepository


def _repository(blackouts: object, weekdays: object) -> PostgresManufacturingCapacityRepository:
    def execute(statement: str, parameters: object = None) -> Any:
        if "FROM reconforge.workcenter_calendars" in statement:
            return SimpleNamespace(fetchone=lambda: ("center", "Synthetic calendar", 60, blackouts, None))
        if "FROM reconforge.workcenter_shifts" in statement:
            return SimpleNamespace(fetchall=lambda: [("shift", "Synthetic shift", 480, 540, 0, weekdays)])
        raise AssertionError("Unexpected SQL in calendar decoder probe")

    repository = PostgresManufacturingCapacityRepository.__new__(PostgresManufacturingCapacityRepository)
    repository.connection = SimpleNamespace(transaction=nullcontext, execute=execute)
    repository.tenant_id = "synthetic-tenant"
    repository._scope = lambda: None  # type: ignore[method-assign]
    return repository


@pytest.mark.parametrize("value", [None, 1, True, {"2026-10-26": True}, '"2026-10-26"',
                                  '{"2026-10-26":true}', "null", "true", [1], [False], [[]],
                                  '{"SECRET-PERSISTED-SENTINEL":'])
def test_invalid_blackout_restrictions_raise_safe_data_quality_error(value: object) -> None:
    with pytest.raises(CapacitySchedulingError) as failure:
        _repository(value, [0, 1]).get_calendar(workspace_id="work", workcenter_id="center")
    assert failure.value.code == "capacity_persisted_data_invalid"
    assert "SECRET-PERSISTED-SENTINEL" not in str(failure.value)


@pytest.mark.parametrize("value", [None, 1, True, {"0": True}, '"01"', '{"0":true}',
                                  "null", "false", [True], [1.5], ["1"], [[]], [7], [-1],
                                  '{"SECRET-PERSISTED-SENTINEL":'])
def test_invalid_weekday_restrictions_raise_safe_data_quality_error(value: object) -> None:
    with pytest.raises(CapacitySchedulingError) as failure:
        _repository(["2026-10-26"], value).get_calendar(workspace_id="work", workcenter_id="center")
    assert failure.value.code == "capacity_persisted_data_invalid"
    assert "SECRET-PERSISTED-SENTINEL" not in str(failure.value)


@pytest.mark.parametrize("value", [["20261026"], ["2026-W44-1"], ["2026-02-30"], ["SECRET-PERSISTED-SENTINEL"]])
def test_blackout_dates_require_valid_canonical_iso_format(value: object) -> None:
    with pytest.raises(CapacitySchedulingError) as failure:
        _repository(value, [0, 1]).get_calendar(workspace_id="work", workcenter_id="center")
    assert failure.value.code == "capacity_persisted_data_invalid"
    assert "SECRET-PERSISTED-SENTINEL" not in str(failure.value)


@pytest.mark.parametrize("representation", ["decoded", "tuple", "json"])
@pytest.mark.parametrize("empty", [False, True])
def test_valid_stored_restrictions_are_preserved(representation: str, empty: bool) -> None:
    dates = [] if empty else ["2026-10-26", "2026-12-31"]
    weekdays = [] if empty else [0, 2, 4]
    values: tuple[object, object] = dates, weekdays
    if representation == "tuple":
        values = tuple(dates), tuple(weekdays)
    elif representation == "json":
        values = json.dumps(dates), json.dumps(weekdays)
    calendar = _repository(*values).get_calendar(workspace_id="work", workcenter_id="center")
    assert calendar is not None
    assert calendar.blackout_dates == frozenset(dates)
    assert calendar.shifts[0].days_of_week == frozenset(weekdays)
