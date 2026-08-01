from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reconforge.domain.scheduling import (
    AmbiguousTimePolicy,
    MisfirePolicy,
    ScheduleDefinition,
    ScheduleFrequency,
    ScheduleInvariantError,
    evaluate_schedule,
)


def _daily(**overrides: object) -> ScheduleDefinition:
    values: dict[str, object] = {
        "schedule_id": "daily-close",
        "version": 1,
        "timezone": "Africa/Cairo",
        "local_hour": 9,
        "local_minute": 30,
        "frequency": ScheduleFrequency.DAILY,
        "start_at": datetime(2026, 1, 1, tzinfo=UTC),
        "misfire_policy": MisfirePolicy.FIRE_ONCE,
    }
    values.update(overrides)
    return ScheduleDefinition(**values)  # type: ignore[arg-type]


def test_schedule_rejects_implicit_time_and_unbounded_or_ambiguous_shape() -> None:
    with pytest.raises(ScheduleInvariantError, match="timezone"):
        _daily(start_at=datetime(2026, 1, 1))
    with pytest.raises(ScheduleInvariantError, match="IANA"):
        _daily(timezone="Mars/Olympus")
    with pytest.raises(ScheduleInvariantError, match="daily schedules"):
        _daily(weekdays=(0,))
    with pytest.raises(ScheduleInvariantError, match="at least one weekday"):
        _daily(frequency=ScheduleFrequency.WEEKLY)
    with pytest.raises(ScheduleInvariantError, match="review boundary"):
        evaluate_schedule(
            _daily(max_lookback_days=1),
            last_evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
            now=datetime(2026, 1, 3, tzinfo=UTC),
        )


def test_daily_schedule_is_timezone_aware_and_dispatch_identity_is_stable() -> None:
    schedule = _daily()
    first = evaluate_schedule(
        schedule,
        last_evaluated_at=datetime(2026, 6, 1, tzinfo=UTC),
        now=datetime(2026, 6, 2, 12, tzinfo=UTC),
    )
    second = evaluate_schedule(
        schedule,
        last_evaluated_at=datetime(2026, 6, 1, tzinfo=UTC),
        now=datetime(2026, 6, 2, 12, tzinfo=UTC),
    )
    assert first == second
    assert first.total_due == 2
    assert first.skipped_count == 1
    assert len(first.dispatch) == 1
    occurrence = first.dispatch[0]
    assert occurrence.local_scheduled_for == "2026-06-02T09:30:00+03:00"
    assert occurrence.scheduled_for_utc == datetime(2026, 6, 2, 6, 30, tzinfo=UTC)
    assert len(occurrence.dispatch_key) == 64


def test_misfire_skip_fire_once_and_bounded_catch_up_have_distinct_cursor_semantics() -> None:
    window = {
        "last_evaluated_at": datetime(2026, 6, 1, tzinfo=UTC),
        "now": datetime(2026, 6, 5, 12, tzinfo=UTC),
    }
    skipped = evaluate_schedule(_daily(misfire_policy=MisfirePolicy.SKIP), **window)
    fired = evaluate_schedule(_daily(misfire_policy=MisfirePolicy.FIRE_ONCE), **window)
    catch_up = evaluate_schedule(
        _daily(misfire_policy=MisfirePolicy.CATCH_UP, max_catch_up=2), **window
    )
    assert (skipped.total_due, skipped.skipped_count, skipped.dispatch) == (5, 5, ())
    assert fired.total_due == 5 and fired.skipped_count == 4 and len(fired.dispatch) == 1
    assert len(catch_up.dispatch) == 2 and catch_up.deferred_count == 3
    assert catch_up.evaluated_through_utc == catch_up.dispatch[-1].scheduled_for_utc
    resumed = evaluate_schedule(
        _daily(misfire_policy=MisfirePolicy.CATCH_UP, max_catch_up=2),
        last_evaluated_at=catch_up.evaluated_through_utc,
        now=window["now"],
    )
    assert {item.dispatch_key for item in resumed.dispatch}.isdisjoint(
        item.dispatch_key for item in catch_up.dispatch
    )


def test_weekly_schedule_canonicalizes_days_and_selects_only_configured_weekdays() -> None:
    schedule = _daily(
        frequency=ScheduleFrequency.WEEKLY,
        weekdays=(4, 0, 4),
        misfire_policy=MisfirePolicy.CATCH_UP,
        max_catch_up=10,
    )
    assert schedule.weekdays == (0, 4)
    result = evaluate_schedule(
        schedule,
        last_evaluated_at=datetime(2026, 6, 1, tzinfo=UTC),
        now=datetime(2026, 6, 8, 12, tzinfo=UTC),
    )
    assert [item.local_scheduled_for[:10] for item in result.dispatch] == [
        "2026-06-01",
        "2026-06-05",
        "2026-06-08",
    ]


def test_dst_gap_is_explicit_and_ambiguous_time_policy_is_reproducible() -> None:
    gap = _daily(
        timezone="America/New_York",
        local_hour=2,
        local_minute=30,
        misfire_policy=MisfirePolicy.CATCH_UP,
        max_catch_up=10,
    )
    gap_result = evaluate_schedule(
        gap,
        last_evaluated_at=datetime(2026, 3, 8, 0, tzinfo=UTC),
        now=datetime(2026, 3, 9, 0, tzinfo=UTC),
    )
    assert gap_result.nonexistent_local_times == 1
    assert gap_result.dispatch == ()

    common = {
        "timezone": "America/New_York",
        "local_hour": 1,
        "local_minute": 30,
        "misfire_policy": MisfirePolicy.CATCH_UP,
        "max_catch_up": 10,
    }
    window = {
        "last_evaluated_at": datetime(2026, 11, 1, 0, tzinfo=UTC),
        "now": datetime(2026, 11, 1, 8, tzinfo=UTC),
    }
    first = evaluate_schedule(_daily(**common, ambiguous_time_policy=AmbiguousTimePolicy.FIRST), **window)
    second = evaluate_schedule(_daily(**common, ambiguous_time_policy=AmbiguousTimePolicy.SECOND), **window)
    assert first.dispatch[0].scheduled_for_utc == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert second.dispatch[0].scheduled_for_utc == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert first.dispatch[0].dispatch_key != second.dispatch[0].dispatch_key
