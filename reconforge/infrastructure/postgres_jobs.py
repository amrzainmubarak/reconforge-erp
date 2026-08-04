"""Tenant-scoped PostgreSQL persistence for the durable-job aggregate."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from reconforge.domain.jobs import (
    DurableJob,
    DurableJobBackpressureError,
    JobLease,
    JobOutputManifest,
    JobPartitionEffect,
    JobStatus,
    JobTransition,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id


class PostgresJobRepositoryError(RuntimeError):
    """Base safe failure for PostgreSQL durable-job persistence."""


class PostgresJobConflictError(PostgresJobRepositoryError):
    """Raised for idempotency conflicts or stale aggregate versions."""


_JOB_COLUMNS = (
    "id",
    "schema_version",
    "version",
    "status",
    "idempotency_scope",
    "idempotency_key",
    "tenant_id",
    "workspace_id",
    "entity_id",
    "input_digest",
    "config_digest",
    "worker_version",
    "completed_units",
    "total_units",
    "checkpoint_digest",
    "retry_count",
    "retry_ceiling",
    "safe_error_code",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "output_manifest_schema_version",
    "output_manifest_digest",
    "output_manifest_reference",
)


def _value(row: Any, name: str, index: int) -> Any:
    return row[name] if isinstance(row, Mapping) else row[index]


def _decode_job(row: Any) -> DurableJob:
    try:
        values = {name: _value(row, name, index) for index, name in enumerate(_JOB_COLUMNS)}
        manifest = None
        if values["output_manifest_schema_version"] is not None:
            manifest = JobOutputManifest(
                schema_version=int(values["output_manifest_schema_version"]),
                digest=str(values["output_manifest_digest"]),
                reference=str(values["output_manifest_reference"]),
            )
        return DurableJob(
            id=str(values["id"]),
            schema_version=int(values["schema_version"]),
            version=int(values["version"]),
            status=JobStatus(str(values["status"])),
            idempotency_scope=str(values["idempotency_scope"]),
            idempotency_key=str(values["idempotency_key"]),
            tenant_id=str(values["tenant_id"]),
            workspace_id=str(values["workspace_id"]),
            entity_id=str(values["entity_id"]),
            input_digest=str(values["input_digest"]),
            config_digest=str(values["config_digest"]),
            worker_version=str(values["worker_version"]),
            completed_units=int(values["completed_units"]),
            total_units=int(values["total_units"]),
            checkpoint_digest=str(values["checkpoint_digest"]),
            retry_count=int(values["retry_count"]),
            retry_ceiling=int(values["retry_ceiling"]),
            safe_error_code=str(values["safe_error_code"]),
            created_at=str(values["created_at"]),
            updated_at=str(values["updated_at"]),
            started_at=str(values["started_at"]),
            completed_at=str(values["completed_at"]),
            output_manifest=manifest,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PostgresJobRepositoryError("Stored durable-job state is invalid.") from exc


def _job_values(job: DurableJob) -> tuple[object, ...]:
    manifest = job.output_manifest
    return (
        job.id,
        job.schema_version,
        job.version,
        job.status.value,
        job.idempotency_scope,
        job.idempotency_key,
        job.tenant_id,
        job.workspace_id,
        job.entity_id,
        job.input_digest,
        job.config_digest,
        job.worker_version,
        job.completed_units,
        job.total_units,
        job.checkpoint_digest,
        job.retry_count,
        job.retry_ceiling,
        job.safe_error_code,
        job.created_at,
        job.updated_at,
        job.started_at,
        job.completed_at,
        None if manifest is None else manifest.schema_version,
        "" if manifest is None else manifest.digest,
        "" if manifest is None else manifest.reference,
    )


def _same_submission(left: DurableJob, right: DurableJob) -> bool:
    fields = (
        "idempotency_scope",
        "idempotency_key",
        "tenant_id",
        "workspace_id",
        "entity_id",
        "input_digest",
        "config_digest",
        "worker_version",
        "total_units",
        "retry_ceiling",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


@dataclass
class PostgresDurableJobRepository:
    """Own an atomic PostgreSQL transaction for every application operation."""

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
        except PostgresJobRepositoryError:
            raise
        except DurableJobBackpressureError:
            raise
        except Exception as exc:
            raise PostgresJobRepositoryError("PostgreSQL durable-job operation failed.") from exc

    def create_or_get(self, job: DurableJob, *, actor_id: str) -> tuple[DurableJob, bool]:
        if job.status is not JobStatus.QUEUED or job.version != 1:
            raise PostgresJobRepositoryError("Only a new queued job may be submitted.")
        columns = ", ".join(_JOB_COLUMNS)
        placeholders = ", ".join("%s" for _ in _JOB_COLUMNS)
        with self._transaction(job.tenant_id, workspace_id=job.workspace_id, entity_id=job.entity_id):
            try:
                inserted = self.connection.execute(
                    # SQL identifiers come only from the immutable module-level _JOB_COLUMNS tuple.
                    f"INSERT INTO reconforge.durable_jobs ({columns}) VALUES ({placeholders}) "  # nosec B608
                    "ON CONFLICT DO NOTHING RETURNING id",
                    _job_values(job),
                ).fetchone()
                if inserted is None:
                    row = self.connection.execute(
                        # SQL identifiers come only from the immutable module-level _JOB_COLUMNS tuple.
                        "SELECT " + columns + " FROM reconforge.durable_jobs "  # nosec B608
                        "WHERE tenant_id=%s AND idempotency_scope=%s AND idempotency_key=%s",
                        (job.tenant_id, job.idempotency_scope, job.idempotency_key),
                    ).fetchone()
                    if row is None:
                        raise PostgresJobConflictError("Idempotent job submission could not be resolved.")
                    existing = _decode_job(row)
                    if not _same_submission(existing, job):
                        raise PostgresJobConflictError(
                            "Idempotency key is already bound to a different job submission."
                        )
                    return existing, False
                self.connection.execute(
                    """
                    INSERT INTO reconforge.durable_job_transitions
                        (tenant_id, job_id, job_version, from_status, to_status,
                         actor_id, occurred_at, reason_code)
                    VALUES (%s, %s, 1, '', 'queued', %s, %s, 'CREATED')
                    """,
                    (job.tenant_id, job.id, actor_id, job.created_at),
                )
            except Exception as exc:
                raise PostgresJobConflictError("Durable job identity or idempotency scope conflicts.") from exc
        return job, True

    def create_or_get_bounded(
        self,
        job: DurableJob,
        *,
        actor_id: str,
        max_queued_jobs: int,
    ) -> tuple[DurableJob, bool]:
        """Submit atomically while bounding queued work in one execution lane.

        A transaction-scoped advisory lock serializes the count-and-insert
        critical section even when the lane has no existing row to lock.
        """

        if isinstance(max_queued_jobs, bool) or not isinstance(max_queued_jobs, int) or max_queued_jobs < 1:
            raise ValueError("max_queued_jobs must be a positive integer")
        if job.status is not JobStatus.QUEUED or job.version != 1:
            raise PostgresJobRepositoryError("Only a new queued job may be submitted.")
        columns = ", ".join(_JOB_COLUMNS)
        placeholders = ", ".join("%s" for _ in _JOB_COLUMNS)
        lane_lock_key = f"reconforge:durable-job-lane:{job.tenant_id}:{job.workspace_id}:{job.entity_id}"
        with self._transaction(job.tenant_id, workspace_id=job.workspace_id, entity_id=job.entity_id):
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (lane_lock_key,),
            )
            try:
                existing_row = self.connection.execute(  # nosec B608
                    "SELECT " + columns + " FROM reconforge.durable_jobs "  # nosec B608
                    "WHERE tenant_id=%s AND idempotency_scope=%s AND idempotency_key=%s",
                    (job.tenant_id, job.idempotency_scope, job.idempotency_key),
                ).fetchone()
                if existing_row is not None:
                    existing = _decode_job(existing_row)
                    if not _same_submission(existing, job):
                        raise PostgresJobConflictError(
                            "Idempotency key is already bound to a different job submission."
                        )
                    return existing, False

                queued = int(
                    self.connection.execute(
                        """
                        SELECT COUNT(*) FROM reconforge.durable_jobs
                        WHERE tenant_id=%s AND workspace_id=%s AND entity_id=%s
                          AND status IN ('queued', 'retrying')
                        """,
                        (job.tenant_id, job.workspace_id, job.entity_id),
                    ).fetchone()[0]
                )
                if queued >= max_queued_jobs:
                    raise DurableJobBackpressureError(
                        "Durable-job execution lane queue capacity has been reached."
                    )

                inserted = self.connection.execute(
                    # SQL identifiers come only from the immutable module-level _JOB_COLUMNS tuple.
                    f"INSERT INTO reconforge.durable_jobs ({columns}) VALUES ({placeholders}) "  # nosec B608
                    "RETURNING id",
                    _job_values(job),
                ).fetchone()
                if inserted is None:
                    raise PostgresJobConflictError("Bounded durable-job insertion returned no identity.")
                self.connection.execute(
                    """
                    INSERT INTO reconforge.durable_job_transitions
                        (tenant_id, job_id, job_version, from_status, to_status,
                         actor_id, occurred_at, reason_code)
                    VALUES (%s, %s, 1, '', 'queued', %s, %s, 'CREATED')
                    """,
                    (job.tenant_id, job.id, actor_id, job.created_at),
                )
            except DurableJobBackpressureError:
                raise
            except PostgresJobConflictError:
                raise
            except Exception as exc:
                raise PostgresJobConflictError("Durable job identity or idempotency scope conflicts.") from exc
        return job, True

    def get(self, *, tenant_id: str, job_id: str) -> DurableJob | None:
        columns = ", ".join(_JOB_COLUMNS)
        with self._transaction(tenant_id):
            row = self.connection.execute(
                # SQL identifiers come only from the immutable module-level _JOB_COLUMNS tuple.
                "SELECT " + columns + " FROM reconforge.durable_jobs WHERE tenant_id = %s AND id = %s",  # nosec B608
                (tenant_id, job_id),
            ).fetchone()
            if row is None:
                return None
            job = _decode_job(row)
            set_local_tenant_scope(self.connection, job.tenant_id, workspace_id=job.workspace_id)
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (job.entity_id,))
            scoped = self.connection.execute(
                "SELECT " + columns + " FROM reconforge.durable_jobs WHERE tenant_id = %s AND id = %s",  # nosec B608
                (tenant_id, job_id),
            ).fetchone()
            return None if scoped is None else _decode_job(scoped)

    def persist_transition(self, previous: DurableJob, changed: DurableJob, event: JobTransition) -> DurableJob:
        if changed.id != previous.id or changed.tenant_id != previous.tenant_id:
            raise PostgresJobRepositoryError("A durable-job transition cannot change job or tenant identity.")
        if changed.version != previous.version + 1 or event.job_version != changed.version:
            raise PostgresJobRepositoryError("A durable-job transition must advance exactly one version.")
        allowed = {
            (JobStatus.QUEUED, JobStatus.CANCELLED),
            (JobStatus.PAUSED, JobStatus.QUEUED),
            (JobStatus.FAILED, JobStatus.QUEUED),
        }
        if (previous.status, changed.status) not in allowed:
            raise PostgresJobConflictError("Worker state changes require a generation-fenced lease.")
        with self._transaction(
            previous.tenant_id,
            workspace_id=previous.workspace_id,
            entity_id=previous.entity_id,
        ):
            lease = self.connection.execute(
                "SELECT 1 FROM reconforge.durable_job_leases WHERE tenant_id = %s AND job_id = %s",
                (previous.tenant_id, previous.id),
            ).fetchone()
            if lease is not None:
                raise PostgresJobConflictError("Leased durable jobs require an owned transition.")
            self._persist_transition_rows(previous, changed, event)
        return changed

    @staticmethod
    def _validate_transition(previous: DurableJob, changed: DurableJob, event: JobTransition) -> None:
        if changed.id != previous.id or changed.tenant_id != previous.tenant_id:
            raise PostgresJobRepositoryError("A durable-job transition cannot change job or tenant identity.")
        if changed.version != previous.version + 1:
            raise PostgresJobRepositoryError("A durable-job transition must advance exactly one version.")
        if (
            event.job_id != changed.id
            or event.job_version != changed.version
            or event.from_status is not previous.status
            or event.to_status is not changed.status
        ):
            raise PostgresJobRepositoryError("Transition evidence does not match the durable-job versions.")

    def _persist_transition_rows(self, previous: DurableJob, changed: DurableJob, event: JobTransition) -> None:
        self._validate_transition(previous, changed, event)
        assignments = ", ".join(f"{column} = %s" for column in _JOB_COLUMNS[1:])
        cursor = self.connection.execute(
            # SQL identifiers come only from the immutable module-level _JOB_COLUMNS tuple.
            f"UPDATE reconforge.durable_jobs SET {assignments} "  # nosec B608
            "WHERE tenant_id = %s AND id = %s AND version = %s",
            (*_job_values(changed)[1:], previous.tenant_id, previous.id, previous.version),
        )
        if cursor.rowcount != 1:
            raise PostgresJobConflictError("Durable job changed before this transition could commit.")
        self.connection.execute(
            """
            INSERT INTO reconforge.durable_job_transitions
                (tenant_id, job_id, job_version, from_status, to_status,
                 actor_id, occurred_at, reason_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                previous.tenant_id,
                event.job_id,
                event.job_version,
                event.from_status.value,
                event.to_status.value,
                event.actor_id,
                event.occurred_at,
                event.reason_code,
            ),
        )

    def _append_lease_event(self, lease: JobLease, *, action: str, occurred_at: str) -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.durable_job_lease_events
                (tenant_id, job_id, event_sequence, generation, action, owner_id, occurred_at, expires_at)
            SELECT %s, %s, COALESCE(MAX(event_sequence), 0) + 1, %s, %s, %s, %s, %s
            FROM reconforge.durable_job_lease_events
            WHERE tenant_id = %s AND job_id = %s
            """,
            (
                lease.tenant_id,
                lease.job_id,
                lease.generation,
                action,
                lease.owner_id,
                occurred_at,
                "" if action == "released" else lease.expires_at,
                lease.tenant_id,
                lease.job_id,
            ),
        )

    def claim_next(
        self,
        *,
        tenant_id: str,
        workspace_id: str | None = None,
        entity_id: str | None = None,
        worker_id: str,
        occurred_at: str,
        lease_expires_at: str,
    ) -> tuple[DurableJob, JobLease] | None:
        columns = ", ".join(f"jobs.{column}" for column in _JOB_COLUMNS)
        with self._transaction(
            tenant_id,
            workspace_id=workspace_id or "",
            entity_id=entity_id or "",
        ):
            row = self.connection.execute(
                f"""
                SELECT {columns}, COALESCE((
                    SELECT MAX(events.generation) FROM reconforge.durable_job_lease_events events
                    WHERE events.tenant_id = jobs.tenant_id AND events.job_id = jobs.id
                ), 0) AS prior_lease_generation
                FROM reconforge.durable_jobs jobs
                LEFT JOIN reconforge.durable_job_leases leases
                  ON leases.tenant_id = jobs.tenant_id AND leases.job_id = jobs.id
                WHERE jobs.tenant_id = %s
                  AND (%s::text IS NULL OR jobs.workspace_id = %s::text)
                  AND (%s::text IS NULL OR jobs.entity_id = %s::text)
                  AND (
                    jobs.status = 'queued'
                    OR (jobs.status = 'retrying' AND (leases.job_id IS NULL OR leases.expires_at <= %s))
                    OR (jobs.status = 'running' AND (leases.job_id IS NULL OR leases.expires_at <= %s))
                )
                ORDER BY CASE jobs.status WHEN 'running' THEN 0 WHEN 'retrying' THEN 1 ELSE 2 END,
                         jobs.created_at, jobs.id
                FOR UPDATE OF jobs SKIP LOCKED LIMIT 1
                """,  # nosec B608
                (
                    tenant_id,
                    workspace_id,
                    workspace_id,
                    entity_id,
                    entity_id,
                    occurred_at,
                    occurred_at,
                ),
            ).fetchone()
            if row is None:
                return None
            previous = _decode_job(row)
            set_local_tenant_scope(self.connection, previous.tenant_id, workspace_id=previous.workspace_id)
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (previous.entity_id,))
            # Re-read the lease after locking the job row.  Under concurrent
            # PostgreSQL plans a LEFT JOIN can expose a stale/missing lease
            # snapshot; never turn that into a takeover while an active lease
            # is still present.  The worker will retry the claim and only a
            # genuinely expired lease can be reclaimed.
            active_lease = self.connection.execute(
                """
                SELECT owner_id, generation, expires_at
                FROM reconforge.durable_job_leases
                WHERE tenant_id=%s AND job_id=%s
                FOR UPDATE
                """,
                (previous.tenant_id, previous.id),
            ).fetchone()
            if previous.status in {JobStatus.RUNNING, JobStatus.RETRYING} and active_lease is not None:
                active_expires_at = str(_value(active_lease, "expires_at", 2))
                if active_expires_at > occurred_at:
                    return None
            if previous.status in {JobStatus.QUEUED, JobStatus.RETRYING}:
                changed, event = previous.transition(
                    JobStatus.RUNNING, actor_id=worker_id, occurred_at=occurred_at, reason_code="CLAIMED"
                )
                action = "claimed"
            else:
                changed, event = previous.reclaim(actor_id=worker_id, occurred_at=occurred_at)
                action = "taken_over"
            generation = int(_value(row, "prior_lease_generation", len(_JOB_COLUMNS))) + 1
            lease = JobLease(
                job_id=changed.id,
                tenant_id=changed.tenant_id,
                owner_id=worker_id,
                generation=generation,
                acquired_at=occurred_at,
                renewed_at=occurred_at,
                expires_at=lease_expires_at,
            )
            self._persist_transition_rows(previous, changed, event)
            self.connection.execute(
                """
                INSERT INTO reconforge.durable_job_leases
                    (tenant_id, job_id, owner_id, generation, acquired_at, renewed_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, job_id) DO UPDATE SET
                    owner_id=excluded.owner_id, generation=excluded.generation,
                    acquired_at=excluded.acquired_at, renewed_at=excluded.renewed_at,
                    expires_at=excluded.expires_at
                """,
                (
                    lease.tenant_id,
                    lease.job_id,
                    lease.owner_id,
                    lease.generation,
                    lease.acquired_at,
                    lease.renewed_at,
                    lease.expires_at,
                ),
            )
            self._append_lease_event(lease, action=action, occurred_at=occurred_at)
            return changed, lease

    def renew_lease(self, lease: JobLease, *, occurred_at: str, lease_expires_at: str) -> JobLease:
        renewed = JobLease(
            job_id=lease.job_id,
            tenant_id=lease.tenant_id,
            owner_id=lease.owner_id,
            generation=lease.generation,
            acquired_at=lease.acquired_at,
            renewed_at=occurred_at,
            expires_at=lease_expires_at,
        )
        if occurred_at >= lease.expires_at or renewed.expires_at <= lease.expires_at:
            raise PostgresJobConflictError("Durable-job lease is expired or was not extended.")
        with self._transaction(lease.tenant_id):
            scope_row = self.connection.execute(
                "SELECT workspace_id, entity_id FROM reconforge.durable_jobs WHERE tenant_id=%s AND id=%s",
                (lease.tenant_id, lease.job_id),
            ).fetchone()
            if scope_row is None:
                raise PostgresJobConflictError("Durable-job lease target no longer exists.")
            set_local_tenant_scope(self.connection, lease.tenant_id, workspace_id=str(scope_row[0]))
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (str(scope_row[1]),))
            cursor = self.connection.execute(
                """
                UPDATE reconforge.durable_job_leases SET renewed_at=%s, expires_at=%s
                WHERE tenant_id=%s AND job_id=%s AND owner_id=%s AND generation=%s AND expires_at>%s
                """,
                (
                    renewed.renewed_at,
                    renewed.expires_at,
                    renewed.tenant_id,
                    renewed.job_id,
                    renewed.owner_id,
                    renewed.generation,
                    occurred_at,
                ),
            )
            if cursor.rowcount != 1:
                raise PostgresJobConflictError("Durable-job lease ownership changed or expired.")
            self._append_lease_event(renewed, action="renewed", occurred_at=occurred_at)
        return renewed

    def _require_owned(self, previous: DurableJob, lease: JobLease, occurred_at: str) -> None:
        owned = self.connection.execute(
            """
            SELECT 1 FROM reconforge.durable_job_leases
            WHERE tenant_id=%s AND job_id=%s AND owner_id=%s AND generation=%s AND expires_at>%s
            FOR UPDATE
            """,
            (lease.tenant_id, lease.job_id, lease.owner_id, lease.generation, occurred_at),
        ).fetchone()
        if owned is None or previous.id != lease.job_id or previous.tenant_id != lease.tenant_id:
            raise PostgresJobConflictError("Durable-job lease ownership changed or expired.")

    def _lock_job(self, job: DurableJob) -> None:
        """Acquire the aggregate row before its lease row.

        Claiming already follows the job-then-lease order.  Completion used to
        take the inverse lease-then-job order, which allowed PostgreSQL to
        deadlock a worker reclaiming an expired job with its current owner
        finishing a partition.  Every transition now follows one lock order.
        """

        row = self.connection.execute(
            "SELECT 1 FROM reconforge.durable_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (job.tenant_id, job.id),
        ).fetchone()
        if row is None:
            raise PostgresJobConflictError("Durable-job target no longer exists.")

    def _release(self, lease: JobLease, *, occurred_at: str) -> None:
        cursor = self.connection.execute(
            "DELETE FROM reconforge.durable_job_leases "
            "WHERE tenant_id=%s AND job_id=%s AND owner_id=%s AND generation=%s",
            (lease.tenant_id, lease.job_id, lease.owner_id, lease.generation),
        )
        if cursor.rowcount != 1:
            raise PostgresJobConflictError("Durable-job lease ownership changed before release.")
        self._append_lease_event(lease, action="released", occurred_at=occurred_at)

    def persist_owned_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
        *,
        lease: JobLease,
        release_lease: bool,
    ) -> DurableJob:
        self._validate_transition(previous, changed, event)
        with self._transaction(
            previous.tenant_id,
            workspace_id=previous.workspace_id,
            entity_id=previous.entity_id,
        ):
            self._lock_job(previous)
            self._require_owned(previous, lease, event.occurred_at)
            self._persist_transition_rows(previous, changed, event)
            if release_lease:
                self._release(lease, occurred_at=event.occurred_at)
        return changed

    def persist_owned_effect_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
        effect: JobPartitionEffect,
        *,
        lease: JobLease,
        release_lease: bool,
    ) -> DurableJob:
        self._validate_transition(previous, changed, event)
        if effect.job_id != changed.id or effect.completed_units != changed.completed_units:
            raise PostgresJobRepositoryError("Partition effect does not match durable-job progress.")
        if effect.committed_at != event.occurred_at:
            raise PostgresJobRepositoryError("Partition effect time does not match transition evidence.")
        with self._transaction(
            previous.tenant_id,
            workspace_id=previous.workspace_id,
            entity_id=previous.entity_id,
        ):
            self._lock_job(previous)
            self._require_owned(previous, lease, event.occurred_at)
            row = self.connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM reconforge.durable_job_partition_effects "
                "WHERE tenant_id=%s AND job_id=%s",
                (previous.tenant_id, effect.job_id),
            ).fetchone()
            if int(row[0]) != effect.ordinal:
                raise PostgresJobConflictError("Partition effect ordinal is not the next committed effect.")
            try:
                self.connection.execute(
                    """
                    INSERT INTO reconforge.durable_job_partition_effects
                        (tenant_id, job_id, partition_key, ordinal, completed_units, input_digest,
                         output_digest, effect_reference, committed_at, job_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        previous.tenant_id,
                        effect.job_id,
                        effect.partition_key,
                        effect.ordinal,
                        effect.completed_units,
                        effect.input_digest,
                        effect.output_digest,
                        effect.effect_reference,
                        effect.committed_at,
                        changed.version,
                    ),
                )
            except Exception as exc:
                raise PostgresJobConflictError("Durable-job partition effect conflicts with committed state.") from exc
            self._persist_transition_rows(previous, changed, event)
            if release_lease:
                self._release(lease, occurred_at=event.occurred_at)
        return changed

    def list_partition_effects(self, *, tenant_id: str, job_id: str) -> list[JobPartitionEffect]:
        with self._transaction(tenant_id):
            scope_row = self.connection.execute(
                "SELECT workspace_id, entity_id FROM reconforge.durable_jobs WHERE tenant_id=%s AND id=%s",
                (tenant_id, job_id),
            ).fetchone()
            if scope_row is None:
                return []
            set_local_tenant_scope(self.connection, tenant_id, workspace_id=str(scope_row[0]))
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (str(scope_row[1]),))
            rows = self.connection.execute(
                """
                SELECT job_id, partition_key, ordinal, completed_units, input_digest,
                       output_digest, effect_reference, committed_at
                FROM reconforge.durable_job_partition_effects
                WHERE tenant_id=%s AND job_id=%s ORDER BY ordinal
                """,
                (tenant_id, job_id),
            ).fetchall()
            return [
                JobPartitionEffect(
                    job_id=str(row[0]),
                    partition_key=str(row[1]),
                    ordinal=int(row[2]),
                    completed_units=int(row[3]),
                    input_digest=str(row[4]),
                    output_digest=str(row[5]),
                    effect_reference=str(row[6]),
                    committed_at=str(row[7]),
                )
                for row in rows
            ]

    def list_transitions(self, *, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._transaction(tenant_id):
            scope_row = self.connection.execute(
                "SELECT workspace_id, entity_id FROM reconforge.durable_jobs WHERE tenant_id=%s AND id=%s",
                (tenant_id, job_id),
            ).fetchone()
            if scope_row is None:
                return []
            set_local_tenant_scope(self.connection, tenant_id, workspace_id=str(scope_row[0]))
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (str(scope_row[1]),))
            cursor = self.connection.execute(
                """
                SELECT job_version, from_status, to_status, actor_id, occurred_at, reason_code
                FROM reconforge.durable_job_transitions
                WHERE tenant_id=%s AND job_id=%s ORDER BY job_version
                """,
                (tenant_id, job_id),
            )
            names = ("job_version", "from_status", "to_status", "actor_id", "occurred_at", "reason_code")
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def list_lease_events(self, *, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._transaction(tenant_id):
            scope_row = self.connection.execute(
                "SELECT workspace_id, entity_id FROM reconforge.durable_jobs WHERE tenant_id=%s AND id=%s",
                (tenant_id, job_id),
            ).fetchone()
            if scope_row is None:
                return []
            set_local_tenant_scope(self.connection, tenant_id, workspace_id=str(scope_row[0]))
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (str(scope_row[1]),))
            cursor = self.connection.execute(
                """
                SELECT event_sequence, generation, action, owner_id, occurred_at, expires_at
                FROM reconforge.durable_job_lease_events
                WHERE tenant_id=%s AND job_id=%s ORDER BY event_sequence
                """,
                (tenant_id, job_id),
            )
            names = ("event_sequence", "generation", "action", "owner_id", "occurred_at", "expires_at")
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


POSTGRES_DURABLE_JOB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.durable_jobs (
    id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    version BIGINT NOT NULL CHECK (version > 0),
    status TEXT NOT NULL CHECK (status IN ('queued','running','paused','retrying','failed','completed','cancelled')),
    idempotency_scope TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL, entity_id TEXT NOT NULL DEFAULT '',
    input_digest TEXT NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    config_digest TEXT NOT NULL CHECK (config_digest ~ '^[0-9a-f]{64}$'),
    worker_version TEXT NOT NULL,
    completed_units BIGINT NOT NULL CHECK (completed_units >= 0),
    total_units BIGINT NOT NULL CHECK (total_units >= 0 AND completed_units <= total_units),
    checkpoint_digest TEXT NOT NULL DEFAULT '' CHECK (checkpoint_digest = '' OR checkpoint_digest ~ '^[0-9a-f]{64}$'),
    retry_count INTEGER NOT NULL CHECK (retry_count >= 0),
    retry_ceiling INTEGER NOT NULL CHECK (retry_ceiling >= retry_count),
    safe_error_code TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '', completed_at TEXT NOT NULL DEFAULT '',
    output_manifest_schema_version INTEGER,
    output_manifest_digest TEXT NOT NULL DEFAULT '', output_manifest_reference TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, idempotency_scope, idempotency_key)
);
CREATE TABLE IF NOT EXISTS reconforge.durable_job_transitions (
    tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, job_version BIGINT NOT NULL,
    from_status TEXT NOT NULL, to_status TEXT NOT NULL, actor_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL, reason_code TEXT NOT NULL,
    PRIMARY KEY (tenant_id, job_id, job_version),
    FOREIGN KEY (tenant_id, job_id) REFERENCES reconforge.durable_jobs(tenant_id, id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.durable_job_leases (
    tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    generation BIGINT NOT NULL CHECK (generation > 0), acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES reconforge.durable_jobs(tenant_id, id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.durable_job_lease_events (
    tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, event_sequence BIGINT NOT NULL,
    generation BIGINT NOT NULL CHECK (generation > 0),
    action TEXT NOT NULL CHECK (action IN ('claimed','renewed','taken_over','released')),
    owner_id TEXT NOT NULL, occurred_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, job_id, event_sequence),
    FOREIGN KEY (tenant_id, job_id) REFERENCES reconforge.durable_jobs(tenant_id, id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.durable_job_partition_effects (
    tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, partition_key TEXT NOT NULL,
    ordinal BIGINT NOT NULL CHECK (ordinal > 0), completed_units BIGINT NOT NULL CHECK (completed_units > 0),
    input_digest TEXT NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    output_digest TEXT NOT NULL CHECK (output_digest ~ '^[0-9a-f]{64}$'),
    effect_reference TEXT NOT NULL, committed_at TEXT NOT NULL, job_version BIGINT NOT NULL,
    PRIMARY KEY (tenant_id, job_id, partition_key),
    UNIQUE (tenant_id, job_id, ordinal),
    UNIQUE (tenant_id, job_id, job_version),
    FOREIGN KEY (tenant_id, job_id) REFERENCES reconforge.durable_jobs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, job_id, job_version)
      REFERENCES reconforge.durable_job_transitions(tenant_id, job_id, job_version) DEFERRABLE INITIALLY DEFERRED
);
CREATE OR REPLACE FUNCTION reconforge.reject_durable_job_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Durable-job evidence is append-only'; END;
$$;
DROP TRIGGER IF EXISTS durable_job_transitions_immutable ON reconforge.durable_job_transitions;
CREATE TRIGGER durable_job_transitions_immutable BEFORE UPDATE OR DELETE ON reconforge.durable_job_transitions
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_durable_job_evidence_mutation();
DROP TRIGGER IF EXISTS durable_job_lease_events_immutable ON reconforge.durable_job_lease_events;
CREATE TRIGGER durable_job_lease_events_immutable BEFORE UPDATE OR DELETE ON reconforge.durable_job_lease_events
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_durable_job_evidence_mutation();
DROP TRIGGER IF EXISTS durable_job_partition_effects_immutable ON reconforge.durable_job_partition_effects;
CREATE TRIGGER durable_job_partition_effects_immutable BEFORE UPDATE OR DELETE ON reconforge.durable_job_partition_effects
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_durable_job_evidence_mutation();
ALTER TABLE reconforge.durable_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_transitions FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_leases FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_lease_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_lease_events FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_partition_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.durable_job_partition_effects FORCE ROW LEVEL SECURITY;
DO $reconforge$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['durable_jobs','durable_job_transitions','durable_job_leases','durable_job_lease_events','durable_job_partition_effects'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
      EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
    END IF;
  END LOOP;
END $reconforge$;
"""


def install_postgres_durable_job_schema(connection: Any) -> None:
    """Install the additive PostgreSQL durable-job schema."""

    connection.execute(POSTGRES_DURABLE_JOB_SCHEMA_SQL)
