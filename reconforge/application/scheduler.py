"""Application contracts for durable schedule registration and dispatch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from reconforge.domain.scheduling import ScheduleDefinition

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class SchedulerError(ValueError):
    """Raised for bounded scheduler validation and persistence failures."""


def _identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise SchedulerError(f"{field_name} is invalid or exceeds 160 characters.")
    return normalized


@dataclass(frozen=True)
class ScheduleJobTemplate:
    """Immutable durable-job fields copied into each occurrence dispatch."""

    job_type: str
    input_digest: str
    config_digest: str
    worker_version: str
    total_units: int
    retry_ceiling: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_type", _identifier(self.job_type, "job_type"))
        object.__setattr__(self, "worker_version", _identifier(self.worker_version, "worker_version"))
        if not _DIGEST.fullmatch(self.input_digest):
            raise SchedulerError("input_digest must be a lowercase SHA-256 digest.")
        if not _DIGEST.fullmatch(self.config_digest):
            raise SchedulerError("config_digest must be a lowercase SHA-256 digest.")
        if not 1 <= self.total_units <= 1_000_000_000:
            raise SchedulerError("total_units must be between 1 and 1000000000.")
        if not 0 <= self.retry_ceiling <= 100:
            raise SchedulerError("retry_ceiling must be between 0 and 100.")


@dataclass(frozen=True)
class ScheduleRegistration:
    """Validated registration request for one tenant/workspace schedule."""

    tenant_id: str
    workspace_id: str
    entity_id: str
    definition: ScheduleDefinition
    job: ScheduleJobTemplate
    cursor_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "workspace_id", _identifier(self.workspace_id, "workspace_id"))
        if self.entity_id:
            object.__setattr__(self, "entity_id", _identifier(self.entity_id, "entity_id"))
        if self.cursor_at.tzinfo is None or self.cursor_at.utcoffset() is None:
            raise SchedulerError("cursor_at must include a timezone.")
        if self.cursor_at.microsecond:
            raise SchedulerError("cursor_at must use whole-second precision.")
        cursor = self.cursor_at.astimezone(UTC)
        if self.definition.start_at - cursor > timedelta(days=self.definition.max_lookback_days):
            raise SchedulerError("cursor_at exceeds the schedule review boundary.")
        object.__setattr__(self, "cursor_at", cursor)


@dataclass(frozen=True)
class ScheduleRecord:
    """Current durable schedule snapshot."""

    registration: ScheduleRegistration
    row_version: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ScheduleDispatch:
    """Immutable mapping from one occurrence to one durable job."""

    tenant_id: str
    schedule_id: str
    schedule_version: int
    dispatch_key: str
    scheduled_for: datetime
    durable_job_id: str
    created_at: datetime


@dataclass(frozen=True)
class ScheduleProcessResult:
    """Bounded counts from one atomic scheduler poll."""

    schedules_claimed: int
    schedules_evaluated: int
    occurrences_due: int
    dispatched: int
    replayed: int
    skipped: int
    deferred: int
    nonexistent_local_times: int


class ScheduleRepositoryProtocol(Protocol):
    def register(self, registration: ScheduleRegistration, *, actor_id: str) -> tuple[ScheduleRecord, bool]: ...

    def get(self, *, tenant_id: str, schedule_id: str) -> ScheduleRecord | None: ...

    def list_dispatches(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        limit: int = 100,
    ) -> list[ScheduleDispatch]: ...

    def process_due(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        now: datetime,
        limit: int = 50,
    ) -> ScheduleProcessResult: ...


class SchedulerApplicationService:
    """Backend-neutral orchestration over an atomic schedule repository."""

    def __init__(self, repository: ScheduleRepositoryProtocol) -> None:
        self.repository = repository

    def register(self, registration: ScheduleRegistration, *, actor_id: str) -> tuple[ScheduleRecord, bool]:
        return self.repository.register(registration, actor_id=_identifier(actor_id, "actor_id"))

    def get(self, *, tenant_id: str, schedule_id: str) -> ScheduleRecord | None:
        return self.repository.get(
            tenant_id=_identifier(tenant_id, "tenant_id"),
            schedule_id=_identifier(schedule_id, "schedule_id"),
        )

    def list_dispatches(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        limit: int = 100,
    ) -> list[ScheduleDispatch]:
        if not 1 <= limit <= 1_000:
            raise SchedulerError("limit must be between 1 and 1000.")
        return self.repository.list_dispatches(
            tenant_id=_identifier(tenant_id, "tenant_id"),
            schedule_id=_identifier(schedule_id, "schedule_id"),
            limit=limit,
        )

    def process_due(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        now: datetime,
        limit: int = 50,
    ) -> ScheduleProcessResult:
        if not 1 <= limit <= 1_000:
            raise SchedulerError("limit must be between 1 and 1000.")
        return self.repository.process_due(
            tenant_id=_identifier(tenant_id, "tenant_id"),
            worker_id=_identifier(worker_id, "worker_id"),
            now=now,
            limit=limit,
        )
