"""PostgreSQL persistence and atomic durable-job dispatch for schedules."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from reconforge.application.notifications import NotificationRequest
from reconforge.application.scheduler import (
    ScheduleDispatch,
    ScheduleJobTemplate,
    ScheduleProcessResult,
    ScheduleRecord,
    ScheduleRegistration,
    SchedulerError,
)
from reconforge.domain.jobs import DurableJob
from reconforge.domain.scheduling import (
    AmbiguousTimePolicy,
    MisfirePolicy,
    ScheduleDefinition,
    ScheduleFrequency,
    ScheduleInvariantError,
    evaluate_schedule,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository, PostgresJobRepositoryError


class PostgresSchedulerError(RuntimeError):
    """Safe PostgreSQL scheduler failure without stored-data disclosure."""


class PostgresSchedulerConflictError(PostgresSchedulerError):
    """Raised for version, identity, or idempotency conflicts."""


class PostgresScheduleReviewRequired(PostgresSchedulerError):
    """Raised when an operator must review an excessive schedule lookback."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


_SCHEDULE_COLUMNS = (
    "tenant_id",
    "schedule_id",
    "schedule_version",
    "workspace_id",
    "entity_id",
    "timezone",
    "local_hour",
    "local_minute",
    "frequency",
    "weekdays",
    "start_at",
    "end_at",
    "misfire_policy",
    "max_catch_up",
    "ambiguous_time_policy",
    "max_lookback_days",
    "job_type",
    "input_digest",
    "config_digest",
    "worker_version",
    "total_units",
    "retry_ceiling",
    "initial_cursor_at",
    "cursor_at",
    "registration_digest",
    "enabled",
    "row_version",
    "created_at",
    "updated_at",
)


def _value(row: Any, name: str, index: int) -> Any:
    return row[name] if isinstance(row, Mapping) else row[index]


def _identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise SchedulerError(f"{field_name} is invalid or exceeds 160 characters.")
    return normalized


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchedulerError(f"{field_name} must include a timezone.")
    if value.microsecond:
        raise SchedulerError(f"{field_name} must use whole-second precision.")
    return value.astimezone(UTC)


def _canonical_timestamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat(timespec="seconds").replace("+00:00", "Z")


def _registration_payload(
    registration: ScheduleRegistration,
    *,
    initial_cursor_at: datetime | None = None,
) -> dict[str, object]:
    definition = registration.definition
    return {
        "tenant_id": registration.tenant_id,
        "workspace_id": registration.workspace_id,
        "entity_id": registration.entity_id,
        "schedule_id": definition.schedule_id,
        "schedule_version": definition.version,
        "timezone": definition.timezone,
        "local_hour": definition.local_hour,
        "local_minute": definition.local_minute,
        "frequency": definition.frequency.value,
        "weekdays": list(definition.weekdays),
        "start_at": _canonical_timestamp(definition.start_at),
        "end_at": None if definition.end_at is None else _canonical_timestamp(definition.end_at),
        "misfire_policy": definition.misfire_policy.value,
        "max_catch_up": definition.max_catch_up,
        "ambiguous_time_policy": definition.ambiguous_time_policy.value,
        "max_lookback_days": definition.max_lookback_days,
        "job_type": registration.job.job_type,
        "input_digest": registration.job.input_digest,
        "config_digest": registration.job.config_digest,
        "worker_version": registration.job.worker_version,
        "total_units": registration.job.total_units,
        "retry_ceiling": registration.job.retry_ceiling,
        "initial_cursor_at": _canonical_timestamp(initial_cursor_at or registration.cursor_at),
    }


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _registration_digest(
    registration: ScheduleRegistration,
    *,
    initial_cursor_at: datetime | None = None,
) -> str:
    return _digest(_registration_payload(registration, initial_cursor_at=initial_cursor_at))


def _event_id(*parts: object) -> str:
    return _digest([str(part) for part in parts])


def _decode_schedule(row: Any) -> ScheduleRecord:
    try:
        values = {name: _value(row, name, index) for index, name in enumerate(_SCHEDULE_COLUMNS)}
        definition = ScheduleDefinition(
            schedule_id=str(values["schedule_id"]),
            version=int(values["schedule_version"]),
            timezone=str(values["timezone"]),
            local_hour=int(values["local_hour"]),
            local_minute=int(values["local_minute"]),
            frequency=ScheduleFrequency(str(values["frequency"])),
            weekdays=tuple(int(day) for day in values["weekdays"]),
            start_at=values["start_at"],
            end_at=values["end_at"],
            misfire_policy=MisfirePolicy(str(values["misfire_policy"])),
            max_catch_up=int(values["max_catch_up"]),
            ambiguous_time_policy=AmbiguousTimePolicy(str(values["ambiguous_time_policy"])),
            max_lookback_days=int(values["max_lookback_days"]),
        )
        registration = ScheduleRegistration(
            tenant_id=str(values["tenant_id"]),
            workspace_id=str(values["workspace_id"]),
            entity_id=str(values["entity_id"]),
            definition=definition,
            job=ScheduleJobTemplate(
                job_type=str(values["job_type"]),
                input_digest=str(values["input_digest"]),
                config_digest=str(values["config_digest"]),
                worker_version=str(values["worker_version"]),
                total_units=int(values["total_units"]),
                retry_ceiling=int(values["retry_ceiling"]),
            ),
            cursor_at=values["cursor_at"],
        )
        if str(values["registration_digest"]) != _registration_digest(
            registration,
            initial_cursor_at=values["initial_cursor_at"],
        ):
            raise PostgresSchedulerError("Stored schedule registration digest is invalid.")
        return ScheduleRecord(
            registration=registration,
            row_version=int(values["row_version"]),
            enabled=bool(values["enabled"]),
            created_at=values["created_at"],
            updated_at=values["updated_at"],
        )
    except (KeyError, TypeError, ValueError, ScheduleInvariantError, SchedulerError) as exc:
        raise PostgresSchedulerError("Stored schedule state is invalid.") from exc


def _schedule_values(registration: ScheduleRegistration) -> tuple[object, ...]:
    definition = registration.definition
    return (
        registration.tenant_id,
        definition.schedule_id,
        definition.version,
        registration.workspace_id,
        registration.entity_id,
        definition.timezone,
        definition.local_hour,
        definition.local_minute,
        definition.frequency.value,
        list(definition.weekdays),
        definition.start_at,
        definition.end_at,
        definition.misfire_policy.value,
        definition.max_catch_up,
        definition.ambiguous_time_policy.value,
        definition.max_lookback_days,
        registration.job.job_type,
        registration.job.input_digest,
        registration.job.config_digest,
        registration.job.worker_version,
        registration.job.total_units,
        registration.job.retry_ceiling,
        registration.cursor_at,
        registration.cursor_at,
        _registration_digest(registration),
    )


@dataclass
class PostgresScheduleRepository:
    """Coordinate schedules and durable jobs in one PostgreSQL transaction."""

    connection: Any

    @contextmanager
    def _transaction(
        self,
        tenant_id: str,
        *,
        workspace_id: str = "",
        entity_id: str = "",
    ) -> Iterator[None]:
        tenant = validate_tenant_id(tenant_id)
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace_id or None)
                self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (entity_id,))
                yield
        except (PostgresSchedulerError, PostgresScheduleReviewRequired):
            raise
        except Exception as exc:
            raise PostgresSchedulerError("PostgreSQL schedule operation failed.") from exc

    def _append_event(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        schedule_version: int,
        event_id: str,
        event_type: str,
        actor_id: str,
        occurred_at: datetime,
        prior_cursor_at: datetime,
        evaluated_through: datetime,
        total_due: int = 0,
        dispatched: int = 0,
        replayed: int = 0,
        skipped: int = 0,
        deferred: int = 0,
        nonexistent_local_times: int = 0,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.schedule_events
              (tenant_id,event_id,schedule_id,schedule_version,event_type,actor_id,occurred_at,
               prior_cursor_at,evaluated_through,total_due,dispatched,replayed,skipped,deferred,
               nonexistent_local_times)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id,event_id) DO NOTHING
            """,
            (
                tenant_id,
                event_id,
                schedule_id,
                schedule_version,
                event_type,
                actor_id,
                occurred_at,
                prior_cursor_at,
                evaluated_through,
                total_due,
                dispatched,
                replayed,
                skipped,
                deferred,
                nonexistent_local_times,
            ),
        )

    def _enqueue_notifications(
        self,
        *,
        registration: ScheduleRegistration,
        dispatch_key: str,
        scheduled_for: datetime,
        durable_job_id: str,
    ) -> int:
        """Atomically enqueue one redacted event per active exact subscription."""

        definition = registration.definition
        routes = self.connection.execute(
            """
            SELECT subscriptions.route_id,subscriptions.route_version,routes.destination_digest
            FROM reconforge.schedule_notification_subscriptions AS subscriptions
            JOIN reconforge.notification_routes AS routes
              ON routes.tenant_id=subscriptions.tenant_id
             AND routes.route_id=subscriptions.route_id
             AND routes.route_version=subscriptions.route_version
            WHERE subscriptions.tenant_id=%s
              AND subscriptions.schedule_id=%s
              AND subscriptions.schedule_version=%s
              AND routes.enabled=TRUE
            ORDER BY subscriptions.route_id,subscriptions.route_version
            """,
            (registration.tenant_id, definition.schedule_id, definition.version),
        ).fetchall()
        enqueued = 0
        for route_id, route_version, route_destination_digest in routes:
            notification_id = _event_id(
                "notification.scheduler_dispatch.v1",
                registration.tenant_id,
                dispatch_key,
                route_id,
                route_version,
            )
            request = NotificationRequest(
                tenant_id=registration.tenant_id,
                notification_id=notification_id,
                route_id=str(route_id),
                route_version=int(route_version),
                destination_digest=str(route_destination_digest),
                workspace_id=registration.workspace_id,
                entity_id=registration.entity_id,
                schedule_id=definition.schedule_id,
                schedule_version=definition.version,
                dispatch_key=dispatch_key,
                scheduled_for=scheduled_for,
                durable_job_id=durable_job_id,
            )
            payload_json = request.canonical_json().decode("ascii")
            inserted = self.connection.execute(
                """
                INSERT INTO reconforge.outbox_events
                  (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES (%s,%s,'notification.scheduler_dispatch.v1','schedule_dispatch',%s,CAST(%s AS jsonb))
                ON CONFLICT (tenant_id,event_id) DO NOTHING
                RETURNING event_id
                """,
                (registration.tenant_id, notification_id, dispatch_key, payload_json),
            ).fetchone()
            if inserted is None:
                existing = self.connection.execute(
                    """
                    SELECT event_type,aggregate_type,aggregate_id,payload
                    FROM reconforge.outbox_events
                    WHERE tenant_id=%s AND event_id=%s
                    """,
                    (registration.tenant_id, notification_id),
                ).fetchone()
                if existing is None or (
                    str(existing[0]),
                    str(existing[1]),
                    str(existing[2]),
                    existing[3],
                ) != (
                    "notification.scheduler_dispatch.v1",
                    "schedule_dispatch",
                    dispatch_key,
                    request.canonical_payload(),
                ):
                    raise PostgresSchedulerConflictError(
                        "Notification outbox identity conflicts with existing state."
                    )
            else:
                enqueued += 1
        return enqueued

    def register(self, registration: ScheduleRegistration, *, actor_id: str) -> tuple[ScheduleRecord, bool]:
        actor_id = _identifier(actor_id, "actor_id")
        digest = _registration_digest(registration)
        definition = registration.definition
        columns = ", ".join(_SCHEDULE_COLUMNS)
        with self._transaction(
            registration.tenant_id,
            workspace_id=registration.workspace_id,
            entity_id=registration.entity_id,
        ):
            rows = self.connection.execute(
                "SELECT " + columns + " FROM reconforge.schedules "  # nosec B608
                "WHERE tenant_id=%s AND schedule_id=%s ORDER BY schedule_version FOR UPDATE",
                (registration.tenant_id, definition.schedule_id),
            ).fetchall()
            for row in rows:
                existing_version = int(_value(row, "schedule_version", 2))
                if existing_version == definition.version:
                    if str(_value(row, "registration_digest", 24)) != digest:
                        raise PostgresSchedulerConflictError(
                            "Schedule version is already bound to a different registration."
                        )
                    return _decode_schedule(row), False
            if rows and definition.version <= max(int(_value(row, "schedule_version", 2)) for row in rows):
                raise PostgresSchedulerConflictError("Schedule versions must increase monotonically.")
            prior_active = [row for row in rows if bool(_value(row, "enabled", 25))]
            for row in prior_active:
                prior = _decode_schedule(row)
                cursor = self.connection.execute(
                    """
                    UPDATE reconforge.schedules
                    SET enabled=FALSE,row_version=row_version+1,updated_at=now()
                    WHERE tenant_id=%s AND schedule_id=%s AND schedule_version=%s
                      AND enabled=TRUE AND row_version=%s
                    """,
                    (
                        registration.tenant_id,
                        definition.schedule_id,
                        prior.registration.definition.version,
                        prior.row_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PostgresSchedulerConflictError("Active schedule version changed during registration.")
                self._append_event(
                    tenant_id=registration.tenant_id,
                    schedule_id=definition.schedule_id,
                    schedule_version=prior.registration.definition.version,
                    event_id=_event_id(
                        "schedule.superseded",
                        registration.tenant_id,
                        definition.schedule_id,
                        prior.registration.definition.version,
                        definition.version,
                    ),
                    event_type="schedule.superseded",
                    actor_id=actor_id,
                    occurred_at=datetime.now(UTC).replace(microsecond=0),
                    prior_cursor_at=prior.registration.cursor_at,
                    evaluated_through=prior.registration.cursor_at,
                )
            insert_columns = _SCHEDULE_COLUMNS[:25]
            placeholders = ",".join("%s" for _ in insert_columns)
            inserted = self.connection.execute(
                f"INSERT INTO reconforge.schedules ({','.join(insert_columns)}) "  # nosec B608
                f"VALUES ({placeholders}) RETURNING {columns}",  # nosec B608
                _schedule_values(registration),
            ).fetchone()
            if inserted is None:
                raise PostgresSchedulerConflictError("Schedule registration did not persist.")
            record = _decode_schedule(inserted)
            self._append_event(
                tenant_id=registration.tenant_id,
                schedule_id=definition.schedule_id,
                schedule_version=definition.version,
                event_id=_event_id(
                    "schedule.registered", registration.tenant_id, definition.schedule_id, definition.version, digest
                ),
                event_type="schedule.registered",
                actor_id=actor_id,
                occurred_at=record.created_at,
                prior_cursor_at=registration.cursor_at,
                evaluated_through=registration.cursor_at,
            )
            return record, True

    def get(self, *, tenant_id: str, schedule_id: str) -> ScheduleRecord | None:
        schedule_id = _identifier(schedule_id, "schedule_id")
        columns = ", ".join(_SCHEDULE_COLUMNS)
        with self._transaction(tenant_id):
            row = self.connection.execute(
                "SELECT " + columns + " FROM reconforge.schedules "  # nosec B608
                "WHERE tenant_id=%s AND schedule_id=%s ORDER BY schedule_version DESC LIMIT 1",
                (tenant_id, schedule_id),
            ).fetchone()
            if row is None:
                return None
            record = _decode_schedule(row)
            set_local_tenant_scope(
                self.connection,
                record.registration.tenant_id,
                workspace_id=record.registration.workspace_id,
            )
            self.connection.execute(
                "SELECT set_config('app.entity_id', %s, true)",
                (record.registration.entity_id,),
            )
            scoped = self.connection.execute(
                "SELECT " + columns + " FROM reconforge.schedules "  # nosec B608
                "WHERE tenant_id=%s AND schedule_id=%s AND schedule_version=%s",
                (tenant_id, schedule_id, record.registration.definition.version),
            ).fetchone()
            return None if scoped is None else _decode_schedule(scoped)

    def list_dispatches(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        limit: int = 100,
    ) -> list[ScheduleDispatch]:
        schedule_id = _identifier(schedule_id, "schedule_id")
        if not 1 <= limit <= 1_000:
            raise SchedulerError("limit must be between 1 and 1000.")
        with self._transaction(tenant_id):
            rows = self.connection.execute(
                """
                SELECT tenant_id,schedule_id,schedule_version,dispatch_key,scheduled_for,durable_job_id,created_at
                FROM reconforge.schedule_dispatches
                WHERE tenant_id=%s AND schedule_id=%s
                ORDER BY scheduled_for,dispatch_key LIMIT %s
                """,
                (tenant_id, schedule_id, limit),
            ).fetchall()
            return [
                ScheduleDispatch(
                    tenant_id=str(row[0]),
                    schedule_id=str(row[1]),
                    schedule_version=int(row[2]),
                    dispatch_key=str(row[3]),
                    scheduled_for=row[4],
                    durable_job_id=str(row[5]),
                    created_at=row[6],
                )
                for row in rows
            ]

    def process_due(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        now: datetime,
        limit: int = 50,
        workspace_id: str | None = None,
        entity_id: str | None = None,
    ) -> ScheduleProcessResult:
        worker_id = _identifier(worker_id, "worker_id")
        if not 1 <= limit <= 1_000:
            raise SchedulerError("limit must be between 1 and 1000.")
        current = _utc(now, "now")
        columns = ", ".join(_SCHEDULE_COLUMNS)
        claimed = evaluated_count = total_due = dispatched = replayed = 0
        skipped = deferred = nonexistent = 0
        normalized_workspace = "" if workspace_id is None else _identifier(workspace_id, "workspace_id")
        normalized_entity = "" if entity_id is None else _identifier(entity_id, "entity_id")
        if normalized_entity and not normalized_workspace:
            raise SchedulerError("entity_id requires workspace_id for scoped processing.")
        with self._transaction(
            tenant_id,
            workspace_id=normalized_workspace,
            entity_id=normalized_entity,
        ):
            query = (
                "SELECT "  # nosec B608 - columns are the closed internal schedule projection.
                + columns
                + " FROM reconforge.schedules "  # nosec B608
                + "WHERE tenant_id=%s AND enabled=TRUE AND cursor_at < %s"
            )
            parameters: list[object] = [tenant_id, current]
            if normalized_workspace:
                query += " AND workspace_id=%s"
                parameters.append(normalized_workspace)
            if normalized_entity:
                query += " AND entity_id=%s"
                parameters.append(normalized_entity)
            query += " ORDER BY cursor_at,schedule_id,schedule_version FOR UPDATE SKIP LOCKED LIMIT %s"
            parameters.append(limit)
            rows = self.connection.execute(query, tuple(parameters)).fetchall()
            claimed = len(rows)
            jobs = PostgresDurableJobRepository(self.connection)
            for row in rows:
                record = _decode_schedule(row)
                registration = record.registration
                definition = registration.definition
                set_local_tenant_scope(
                    self.connection,
                    registration.tenant_id,
                    workspace_id=registration.workspace_id,
                )
                self.connection.execute(
                    "SELECT set_config('app.entity_id', %s, true)",
                    (registration.entity_id,),
                )
                try:
                    evaluation = evaluate_schedule(
                        definition,
                        last_evaluated_at=registration.cursor_at,
                        now=current,
                    )
                except ScheduleInvariantError as exc:
                    raise PostgresScheduleReviewRequired(
                        "Schedule evaluation requires operator review before its cursor can advance."
                    ) from exc
                evaluated_count += 1
                schedule_dispatched = schedule_replayed = 0
                for occurrence in evaluation.dispatch:
                    job_id = "scheduled-job-" + occurrence.dispatch_key[:48]
                    job = DurableJob.queued(
                        job_id=job_id,
                        idempotency_scope=registration.job.job_type,
                        idempotency_key=occurrence.dispatch_key,
                        tenant_id=registration.tenant_id,
                        workspace_id=registration.workspace_id,
                        entity_id=registration.entity_id,
                        input_digest=registration.job.input_digest,
                        config_digest=registration.job.config_digest,
                        worker_version=registration.job.worker_version,
                        total_units=registration.job.total_units,
                        retry_ceiling=registration.job.retry_ceiling,
                        created_at=_canonical_timestamp(current),
                    )
                    try:
                        persisted_job, _ = jobs.create_or_get(job, actor_id=worker_id)
                    except PostgresJobRepositoryError as exc:
                        raise PostgresSchedulerConflictError(
                            "Scheduled durable-job identity conflicts with existing state."
                        ) from exc
                    inserted = self.connection.execute(
                        """
                        INSERT INTO reconforge.schedule_dispatches
                          (tenant_id,schedule_id,schedule_version,dispatch_key,scheduled_for,durable_job_id,worker_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (tenant_id,dispatch_key) DO NOTHING
                        RETURNING dispatch_key
                        """,
                        (
                            registration.tenant_id,
                            definition.schedule_id,
                            definition.version,
                            occurrence.dispatch_key,
                            occurrence.scheduled_for_utc,
                            persisted_job.id,
                            worker_id,
                        ),
                    ).fetchone()
                    if inserted is None:
                        existing = self.connection.execute(
                            """
                            SELECT schedule_id,schedule_version,scheduled_for,durable_job_id
                            FROM reconforge.schedule_dispatches
                            WHERE tenant_id=%s AND dispatch_key=%s
                            """,
                            (registration.tenant_id, occurrence.dispatch_key),
                        ).fetchone()
                        if existing is None or (
                            str(existing[0]), int(existing[1]), existing[2], str(existing[3])
                        ) != (
                            definition.schedule_id,
                            definition.version,
                            occurrence.scheduled_for_utc,
                            persisted_job.id,
                        ):
                            raise PostgresSchedulerConflictError(
                                "Schedule dispatch identity conflicts with existing evidence."
                            )
                        schedule_replayed += 1
                    else:
                        schedule_dispatched += 1
                        self._enqueue_notifications(
                            registration=registration,
                            dispatch_key=occurrence.dispatch_key,
                            scheduled_for=occurrence.scheduled_for_utc,
                            durable_job_id=persisted_job.id,
                        )
                changed = self.connection.execute(
                    """
                    UPDATE reconforge.schedules
                    SET cursor_at=%s,row_version=row_version+1,updated_at=now()
                    WHERE tenant_id=%s AND schedule_id=%s AND schedule_version=%s AND row_version=%s
                    """,
                    (
                        evaluation.evaluated_through_utc,
                        registration.tenant_id,
                        definition.schedule_id,
                        definition.version,
                        record.row_version,
                    ),
                )
                if changed.rowcount != 1:
                    raise PostgresSchedulerConflictError("Schedule cursor changed before dispatch committed.")
                self._append_event(
                    tenant_id=registration.tenant_id,
                    schedule_id=definition.schedule_id,
                    schedule_version=definition.version,
                    event_id=_event_id(
                        "schedule.evaluated",
                        registration.tenant_id,
                        definition.schedule_id,
                        definition.version,
                        _canonical_timestamp(registration.cursor_at),
                        _canonical_timestamp(evaluation.evaluated_through_utc),
                    ),
                    event_type="schedule.evaluated",
                    actor_id=worker_id,
                    occurred_at=current,
                    prior_cursor_at=registration.cursor_at,
                    evaluated_through=evaluation.evaluated_through_utc,
                    total_due=evaluation.total_due,
                    dispatched=schedule_dispatched,
                    replayed=schedule_replayed,
                    skipped=evaluation.skipped_count,
                    deferred=evaluation.deferred_count,
                    nonexistent_local_times=evaluation.nonexistent_local_times,
                )
                total_due += evaluation.total_due
                dispatched += schedule_dispatched
                replayed += schedule_replayed
                skipped += evaluation.skipped_count
                deferred += evaluation.deferred_count
                nonexistent += evaluation.nonexistent_local_times
        return ScheduleProcessResult(
            schedules_claimed=claimed,
            schedules_evaluated=evaluated_count,
            occurrences_due=total_due,
            dispatched=dispatched,
            replayed=replayed,
            skipped=skipped,
            deferred=deferred,
            nonexistent_local_times=nonexistent,
        )


POSTGRES_SCHEDULER_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.schedules (
  tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
  schedule_id TEXT NOT NULL CHECK (schedule_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  schedule_version INTEGER NOT NULL CHECK (schedule_version > 0),
  workspace_id TEXT NOT NULL,
  entity_id TEXT NOT NULL DEFAULT '',
  timezone TEXT NOT NULL CHECK (timezone <> '' AND length(timezone) <= 128),
  local_hour SMALLINT NOT NULL CHECK (local_hour BETWEEN 0 AND 23),
  local_minute SMALLINT NOT NULL CHECK (local_minute BETWEEN 0 AND 59),
  frequency TEXT NOT NULL CHECK (frequency IN ('daily','weekly')),
  weekdays SMALLINT[] NOT NULL DEFAULT '{}'
    CHECK (weekdays <@ ARRAY[0,1,2,3,4,5,6]::SMALLINT[]),
  start_at TIMESTAMPTZ NOT NULL CHECK (start_at=date_trunc('second',start_at)),
  end_at TIMESTAMPTZ CHECK (end_at IS NULL OR (end_at>start_at AND end_at=date_trunc('second',end_at))),
  misfire_policy TEXT NOT NULL CHECK (misfire_policy IN ('skip','fire_once','catch_up')),
  max_catch_up SMALLINT NOT NULL CHECK (max_catch_up BETWEEN 1 AND 100),
  ambiguous_time_policy TEXT NOT NULL CHECK (ambiguous_time_policy IN ('first','second')),
  max_lookback_days SMALLINT NOT NULL CHECK (max_lookback_days BETWEEN 1 AND 3660),
  job_type TEXT NOT NULL CHECK (job_type ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  input_digest TEXT NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
  config_digest TEXT NOT NULL CHECK (config_digest ~ '^[0-9a-f]{64}$'),
  worker_version TEXT NOT NULL CHECK (worker_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  total_units BIGINT NOT NULL CHECK (total_units BETWEEN 1 AND 1000000000),
  retry_ceiling SMALLINT NOT NULL CHECK (retry_ceiling BETWEEN 0 AND 100),
  initial_cursor_at TIMESTAMPTZ NOT NULL CHECK (initial_cursor_at=date_trunc('second',initial_cursor_at)),
  cursor_at TIMESTAMPTZ NOT NULL CHECK (cursor_at=date_trunc('second',cursor_at)),
  registration_digest TEXT NOT NULL CHECK (registration_digest ~ '^[0-9a-f]{64}$'),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  PRIMARY KEY (tenant_id,schedule_id,schedule_version),
  FOREIGN KEY (tenant_id,workspace_id)
    REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE RESTRICT,
  CHECK (cursor_at >= initial_cursor_at),
  CHECK ((frequency='daily' AND cardinality(weekdays)=0) OR
         (frequency='weekly' AND cardinality(weekdays) BETWEEN 1 AND 7))
);
CREATE UNIQUE INDEX IF NOT EXISTS schedules_one_active_version
 ON reconforge.schedules(tenant_id,schedule_id) WHERE enabled;
CREATE INDEX IF NOT EXISTS schedules_due_lookup
 ON reconforge.schedules(tenant_id,enabled,cursor_at,schedule_id,schedule_version);

CREATE TABLE IF NOT EXISTS reconforge.schedule_dispatches (
  tenant_id TEXT NOT NULL,
  schedule_id TEXT NOT NULL,
  schedule_version INTEGER NOT NULL,
  dispatch_key TEXT NOT NULL CHECK (dispatch_key ~ '^[0-9a-f]{64}$'),
  scheduled_for TIMESTAMPTZ NOT NULL CHECK (scheduled_for=date_trunc('second',scheduled_for)),
  durable_job_id TEXT NOT NULL,
  worker_id TEXT NOT NULL CHECK (worker_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  PRIMARY KEY (tenant_id,dispatch_key),
  UNIQUE (tenant_id,schedule_id,schedule_version,scheduled_for),
  UNIQUE (tenant_id,durable_job_id),
  FOREIGN KEY (tenant_id,schedule_id,schedule_version)
    REFERENCES reconforge.schedules(tenant_id,schedule_id,schedule_version) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id,durable_job_id)
    REFERENCES reconforge.durable_jobs(tenant_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.schedule_events (
  tenant_id TEXT NOT NULL,
  event_id TEXT NOT NULL CHECK (event_id ~ '^[0-9a-f]{64}$'),
  schedule_id TEXT NOT NULL,
  schedule_version INTEGER NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('schedule.registered','schedule.superseded','schedule.evaluated')),
  actor_id TEXT NOT NULL CHECK (actor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  occurred_at TIMESTAMPTZ NOT NULL CHECK (occurred_at=date_trunc('second',occurred_at)),
  prior_cursor_at TIMESTAMPTZ NOT NULL CHECK (prior_cursor_at=date_trunc('second',prior_cursor_at)),
  evaluated_through TIMESTAMPTZ NOT NULL CHECK (evaluated_through=date_trunc('second',evaluated_through)),
  total_due INTEGER NOT NULL DEFAULT 0 CHECK (total_due >= 0),
  dispatched INTEGER NOT NULL DEFAULT 0 CHECK (dispatched >= 0),
  replayed INTEGER NOT NULL DEFAULT 0 CHECK (replayed >= 0),
  skipped INTEGER NOT NULL DEFAULT 0 CHECK (skipped >= 0),
  deferred INTEGER NOT NULL DEFAULT 0 CHECK (deferred >= 0),
  nonexistent_local_times INTEGER NOT NULL DEFAULT 0 CHECK (nonexistent_local_times >= 0),
  PRIMARY KEY (tenant_id,event_id),
  FOREIGN KEY (tenant_id,schedule_id,schedule_version)
    REFERENCES reconforge.schedules(tenant_id,schedule_id,schedule_version) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION reconforge.schedule_state_guard() RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'schedule versions cannot be deleted'; END IF;
  IF (NEW.tenant_id,NEW.schedule_id,NEW.schedule_version,NEW.workspace_id,NEW.entity_id,
      NEW.timezone,NEW.local_hour,NEW.local_minute,NEW.frequency,NEW.weekdays,NEW.start_at,NEW.end_at,
      NEW.misfire_policy,NEW.max_catch_up,NEW.ambiguous_time_policy,NEW.max_lookback_days,
      NEW.job_type,NEW.input_digest,NEW.config_digest,NEW.worker_version,NEW.total_units,
      NEW.retry_ceiling,NEW.initial_cursor_at,NEW.registration_digest,NEW.created_at)
     IS DISTINCT FROM
     (OLD.tenant_id,OLD.schedule_id,OLD.schedule_version,OLD.workspace_id,OLD.entity_id,
      OLD.timezone,OLD.local_hour,OLD.local_minute,OLD.frequency,OLD.weekdays,OLD.start_at,OLD.end_at,
      OLD.misfire_policy,OLD.max_catch_up,OLD.ambiguous_time_policy,OLD.max_lookback_days,
      OLD.job_type,OLD.input_digest,OLD.config_digest,OLD.worker_version,OLD.total_units,
      OLD.retry_ceiling,OLD.initial_cursor_at,OLD.registration_digest,OLD.created_at)
  THEN RAISE EXCEPTION 'schedule version configuration is immutable'; END IF;
  IF NEW.cursor_at < OLD.cursor_at THEN RAISE EXCEPTION 'schedule cursor cannot move backward'; END IF;
  IF OLD.enabled=FALSE AND NEW.enabled=TRUE THEN RAISE EXCEPTION 'superseded schedule cannot be re-enabled'; END IF;
  IF NEW.row_version <> OLD.row_version+1 THEN RAISE EXCEPTION 'schedule row version must advance exactly once'; END IF;
  IF NEW.updated_at < OLD.updated_at THEN RAISE EXCEPTION 'schedule update time cannot move backward'; END IF;
  RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS schedules_state_guard ON reconforge.schedules;
CREATE TRIGGER schedules_state_guard BEFORE UPDATE OR DELETE ON reconforge.schedules
 FOR EACH ROW EXECUTE FUNCTION reconforge.schedule_state_guard();

CREATE OR REPLACE FUNCTION reconforge.reject_schedule_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN RAISE EXCEPTION 'schedule dispatch and audit evidence are append-only'; END $reconforge$;
DROP TRIGGER IF EXISTS schedule_dispatches_immutable ON reconforge.schedule_dispatches;
CREATE TRIGGER schedule_dispatches_immutable BEFORE UPDATE OR DELETE ON reconforge.schedule_dispatches
 FOR EACH ROW EXECUTE FUNCTION reconforge.reject_schedule_evidence_mutation();
DROP TRIGGER IF EXISTS schedule_events_immutable ON reconforge.schedule_events;
CREATE TRIGGER schedule_events_immutable BEFORE UPDATE OR DELETE ON reconforge.schedule_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.reject_schedule_evidence_mutation();

ALTER TABLE reconforge.schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedules FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedule_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedule_dispatches FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedule_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedule_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.schedules;
CREATE POLICY tenant_scope ON reconforge.schedules
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL
        OR entity_id=current_setting('app.entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL
        OR entity_id=current_setting('app.entity_id',true)));
DO $reconforge$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['schedule_dispatches','schedule_events'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I',table_name);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I '
      'USING (tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.schedules parent WHERE parent.tenant_id=%1$I.tenant_id '
      'AND parent.schedule_id=%1$I.schedule_id AND parent.schedule_version=%1$I.schedule_version)) '
      'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.schedules parent WHERE parent.tenant_id=%1$I.tenant_id '
      'AND parent.schedule_id=%1$I.schedule_id AND parent.schedule_version=%1$I.schedule_version))',
      table_name
    );
  END LOOP;
END $reconforge$;
"""


def install_postgres_scheduler_schema(connection: Any) -> None:
    """Install the additive durable scheduler schema."""

    connection.execute(POSTGRES_SCHEDULER_SCHEMA_SQL)
