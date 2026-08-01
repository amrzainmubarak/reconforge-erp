"""Deterministic timezone-aware schedule evaluation without network effects."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class ScheduleInvariantError(ValueError):
    """Raised when a schedule cannot be evaluated deterministically and safely."""


class ScheduleFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class MisfirePolicy(str, Enum):
    SKIP = "skip"
    FIRE_ONCE = "fire_once"
    CATCH_UP = "catch_up"


class AmbiguousTimePolicy(str, Enum):
    FIRST = "first"
    SECOND = "second"


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleInvariantError(f"{field_name} must include a timezone.")
    if value.microsecond:
        raise ScheduleInvariantError(f"{field_name} must use whole-second precision.")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ScheduleDefinition:
    """Closed v1 daily/weekly schedule with explicit DST and misfire policy."""

    schedule_id: str
    version: int
    timezone: str
    local_hour: int
    local_minute: int
    frequency: ScheduleFrequency
    start_at: datetime
    weekdays: tuple[int, ...] = ()
    end_at: datetime | None = None
    misfire_policy: MisfirePolicy = MisfirePolicy.FIRE_ONCE
    max_catch_up: int = 1
    ambiguous_time_policy: AmbiguousTimePolicy = AmbiguousTimePolicy.FIRST
    max_lookback_days: int = 366

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.schedule_id):
            raise ScheduleInvariantError("schedule_id is invalid or exceeds 160 characters.")
        if self.version < 1:
            raise ScheduleInvariantError("version must be positive.")
        if not 0 <= self.local_hour <= 23 or not 0 <= self.local_minute <= 59:
            raise ScheduleInvariantError("local schedule time is invalid.")
        if not self.timezone.strip() or len(self.timezone) > 128:
            raise ScheduleInvariantError("timezone is invalid.")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ScheduleInvariantError("timezone is not present in the installed IANA registry.") from exc
        normalized_weekdays = tuple(sorted(set(self.weekdays)))
        if any(day < 0 or day > 6 for day in normalized_weekdays):
            raise ScheduleInvariantError("weekdays must use ISO values from 0 through 6.")
        if self.frequency is ScheduleFrequency.DAILY and normalized_weekdays:
            raise ScheduleInvariantError("daily schedules cannot declare weekdays.")
        if self.frequency is ScheduleFrequency.WEEKLY and not normalized_weekdays:
            raise ScheduleInvariantError("weekly schedules require at least one weekday.")
        if not 1 <= self.max_catch_up <= 100:
            raise ScheduleInvariantError("max_catch_up must be between 1 and 100.")
        if not 1 <= self.max_lookback_days <= 3_660:
            raise ScheduleInvariantError("max_lookback_days must be between 1 and 3660.")
        start = _utc(self.start_at, "start_at")
        end = _utc(self.end_at, "end_at") if self.end_at is not None else None
        if end is not None and end <= start:
            raise ScheduleInvariantError("end_at must be later than start_at.")
        object.__setattr__(self, "start_at", start)
        object.__setattr__(self, "end_at", end)
        object.__setattr__(self, "weekdays", normalized_weekdays)


@dataclass(frozen=True)
class ScheduleOccurrence:
    """One stable schedule occurrence suitable for an idempotency key."""

    schedule_id: str
    schedule_version: int
    scheduled_for_utc: datetime
    local_scheduled_for: str
    timezone: str
    dispatch_key: str


@dataclass(frozen=True)
class ScheduleEvaluation:
    """Bounded result of advancing one durable schedule cursor."""

    dispatch: tuple[ScheduleOccurrence, ...]
    total_due: int
    skipped_count: int
    deferred_count: int
    nonexistent_local_times: int
    evaluated_through_utc: datetime


def _occurrence(schedule: ScheduleDefinition, scheduled_for: datetime, local_text: str) -> ScheduleOccurrence:
    scheduled_utc = scheduled_for.astimezone(UTC)
    identity = json.dumps(
        {
            "schedule_id": schedule.schedule_id,
            "schedule_version": schedule.version,
            "scheduled_for_utc": scheduled_utc.isoformat().replace("+00:00", "Z"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ScheduleOccurrence(
        schedule_id=schedule.schedule_id,
        schedule_version=schedule.version,
        scheduled_for_utc=scheduled_utc,
        local_scheduled_for=local_text,
        timezone=schedule.timezone,
        dispatch_key=hashlib.sha256(identity).hexdigest(),
    )


def _resolve_local(schedule: ScheduleDefinition, local_date: date) -> tuple[datetime, str] | None:
    zone = ZoneInfo(schedule.timezone)
    wall = datetime.combine(local_date, time(schedule.local_hour, schedule.local_minute))
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if round_trip == wall and all(candidate.astimezone(UTC) != item.astimezone(UTC) for item in candidates):
            candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda value: value.astimezone(UTC))
    selected = candidates[-1] if schedule.ambiguous_time_policy is AmbiguousTimePolicy.SECOND else candidates[0]
    return selected, selected.isoformat(timespec="seconds")


def evaluate_schedule(
    schedule: ScheduleDefinition,
    *,
    last_evaluated_at: datetime,
    now: datetime,
) -> ScheduleEvaluation:
    """Evaluate `(last_evaluated_at, now]` with bounded catch-up and explicit DST behavior."""

    cursor = _utc(last_evaluated_at, "last_evaluated_at")
    current = _utc(now, "now")
    if current < cursor:
        raise ScheduleInvariantError("now cannot precede last_evaluated_at.")
    if current - cursor > timedelta(days=schedule.max_lookback_days):
        raise ScheduleInvariantError("schedule lookback exceeds the configured review boundary.")
    if current == cursor:
        return ScheduleEvaluation((), 0, 0, 0, 0, current)

    zone = ZoneInfo(schedule.timezone)
    local_date = cursor.astimezone(zone).date()
    final_date = current.astimezone(zone).date()
    due: list[ScheduleOccurrence] = []
    nonexistent = 0
    while local_date <= final_date:
        selected_day = schedule.frequency is ScheduleFrequency.DAILY or local_date.weekday() in schedule.weekdays
        if selected_day:
            resolved = _resolve_local(schedule, local_date)
            if resolved is None:
                nonexistent += 1
            else:
                scheduled_for, local_text = resolved
                scheduled_utc = scheduled_for.astimezone(UTC)
                if (
                    cursor < scheduled_utc <= current
                    and scheduled_utc >= schedule.start_at
                    and (schedule.end_at is None or scheduled_utc <= schedule.end_at)
                ):
                    due.append(_occurrence(schedule, scheduled_for, local_text))
        local_date += timedelta(days=1)

    due.sort(key=lambda item: (item.scheduled_for_utc, item.dispatch_key))
    if schedule.misfire_policy is MisfirePolicy.SKIP:
        dispatch: tuple[ScheduleOccurrence, ...] = ()
        skipped = len(due)
        deferred = 0
        evaluated_through = current
    elif schedule.misfire_policy is MisfirePolicy.FIRE_ONCE:
        dispatch = tuple(due[-1:])
        skipped = max(0, len(due) - len(dispatch))
        deferred = 0
        evaluated_through = current
    else:
        dispatch = tuple(due[: schedule.max_catch_up])
        skipped = 0
        deferred = max(0, len(due) - len(dispatch))
        evaluated_through = dispatch[-1].scheduled_for_utc if deferred and dispatch else current
    return ScheduleEvaluation(
        dispatch=dispatch,
        total_due=len(due),
        skipped_count=skipped,
        deferred_count=deferred,
        nonexistent_local_times=nonexistent,
        evaluated_through_utc=evaluated_through,
    )
