"""Atomic SQLite persistence for the versioned durable-job aggregate."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from reconforge.domain.jobs import (
    DurableJob,
    JobLease,
    JobOutputManifest,
    JobStatus,
    JobTransition,
)


class SQLiteJobRepositoryError(RuntimeError):
    """Base safe failure for local durable-job persistence."""


class SQLiteJobConflictError(SQLiteJobRepositoryError):
    """Raised on idempotency conflicts or stale aggregate versions."""


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


def _row_value(row: sqlite3.Row, name: str) -> Any:
    return row[name]


def _job_from_row(row: sqlite3.Row) -> DurableJob:
    manifest = None
    manifest_version = _row_value(row, "output_manifest_schema_version")
    if manifest_version is not None:
        manifest = JobOutputManifest(
            schema_version=int(manifest_version),
            digest=str(_row_value(row, "output_manifest_digest")),
            reference=str(_row_value(row, "output_manifest_reference")),
        )
    return DurableJob(
        id=str(_row_value(row, "id")),
        schema_version=int(_row_value(row, "schema_version")),
        version=int(_row_value(row, "version")),
        status=JobStatus(str(_row_value(row, "status"))),
        idempotency_scope=str(_row_value(row, "idempotency_scope")),
        idempotency_key=str(_row_value(row, "idempotency_key")),
        tenant_id=str(_row_value(row, "tenant_id")),
        workspace_id=str(_row_value(row, "workspace_id")),
        entity_id=str(_row_value(row, "entity_id")),
        input_digest=str(_row_value(row, "input_digest")),
        config_digest=str(_row_value(row, "config_digest")),
        worker_version=str(_row_value(row, "worker_version")),
        completed_units=int(_row_value(row, "completed_units")),
        total_units=int(_row_value(row, "total_units")),
        checkpoint_digest=str(_row_value(row, "checkpoint_digest")),
        retry_count=int(_row_value(row, "retry_count")),
        retry_ceiling=int(_row_value(row, "retry_ceiling")),
        safe_error_code=str(_row_value(row, "safe_error_code")),
        created_at=str(_row_value(row, "created_at")),
        updated_at=str(_row_value(row, "updated_at")),
        started_at=str(_row_value(row, "started_at")),
        completed_at=str(_row_value(row, "completed_at")),
        output_manifest=manifest,
    )


def _decode_job(row: sqlite3.Row) -> DurableJob:
    try:
        return _job_from_row(row)
    except (KeyError, TypeError, ValueError) as exc:
        raise SQLiteJobRepositoryError("Stored durable-job state is invalid.") from exc


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
class SQLiteDurableJobRepository:
    """Persist job state and transition evidence in one owned transaction."""

    connection: sqlite3.Connection

    def __post_init__(self) -> None:
        required = {
            "durable_jobs",
            "durable_job_transitions",
            "durable_job_leases",
            "durable_job_lease_events",
        }
        tables = {
            str(row["name"])
            for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not tables >= required:
            raise SQLiteJobRepositoryError("Durable-job schema is unavailable. Run database migrations first.")

    def _begin(self) -> None:
        if self.connection.in_transaction:
            raise SQLiteJobRepositoryError("Durable-job repository requires an unambiguous transaction boundary.")
        self.connection.execute("BEGIN IMMEDIATE")

    def create_or_get(self, job: DurableJob, *, actor_id: str) -> tuple[DurableJob, bool]:
        """Create a queued job or replay the exact scoped idempotent submission."""

        if job.status is not JobStatus.QUEUED or job.version != 1:
            raise SQLiteJobRepositoryError("Only a new queued job may be submitted.")
        creation_event = JobTransition(
            job_id=job.id,
            job_version=1,
            from_status=JobStatus.QUEUED,
            to_status=JobStatus.QUEUED,
            actor_id=actor_id,
            occurred_at=job.created_at,
            reason_code="CREATED",
        )
        self._begin()
        try:
            existing_row = self.connection.execute(
                "SELECT * FROM durable_jobs WHERE tenant_id = ? AND idempotency_scope = ? AND idempotency_key = ?",
                (job.tenant_id, job.idempotency_scope, job.idempotency_key),
            ).fetchone()
            if existing_row is not None:
                existing = _decode_job(existing_row)
                if not _same_submission(existing, job):
                    raise SQLiteJobConflictError("Idempotency key is already bound to a different job submission.")
                self.connection.commit()
                return existing, False

            placeholders = ", ".join("?" for _ in _JOB_COLUMNS)
            self.connection.execute(
                f"INSERT INTO durable_jobs ({', '.join(_JOB_COLUMNS)}) VALUES ({placeholders})",  # noqa: S608
                _job_values(job),
            )
            self.connection.execute(
                """
                INSERT INTO durable_job_transitions
                    (job_id, job_version, from_status, to_status, actor_id, occurred_at, reason_code)
                VALUES (?, 1, '', 'queued', ?, ?, 'CREATED')
                """,
                (job.id, creation_event.actor_id, creation_event.occurred_at),
            )
            self.connection.commit()
            return job, True
        except SQLiteJobConflictError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise SQLiteJobConflictError("Durable job identity or idempotency scope conflicts.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise SQLiteJobRepositoryError("Unable to submit durable job.") from exc

    def get(self, *, tenant_id: str, job_id: str) -> DurableJob | None:
        row = self.connection.execute(
            "SELECT * FROM durable_jobs WHERE tenant_id = ? AND id = ?",
            (tenant_id, job_id),
        ).fetchone()
        return None if row is None else _decode_job(row)

    def persist_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
    ) -> DurableJob:
        """Compare-and-swap one state version and append its evidence atomically."""

        self._validate_transition(previous, changed, event)
        allowed_unleased = {
            (JobStatus.QUEUED, JobStatus.CANCELLED),
            (JobStatus.PAUSED, JobStatus.QUEUED),
            (JobStatus.FAILED, JobStatus.QUEUED),
        }
        if (previous.status, changed.status) not in allowed_unleased:
            raise SQLiteJobConflictError("Worker state changes require a generation-fenced lease.")
        self._begin()
        try:
            lease_row = self.connection.execute(
                "SELECT 1 FROM durable_job_leases WHERE job_id = ?",
                (previous.id,),
            ).fetchone()
            if lease_row is not None:
                raise SQLiteJobConflictError("Leased durable jobs require an owned transition.")
            self._persist_transition_rows(previous, changed, event)
            self.connection.commit()
            return changed
        except SQLiteJobConflictError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise SQLiteJobConflictError("Durable-job transition conflicts with stored evidence.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise SQLiteJobRepositoryError("Unable to persist durable-job transition.") from exc

    @staticmethod
    def _validate_transition(
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
    ) -> None:
        if changed.id != previous.id or changed.tenant_id != previous.tenant_id:
            raise SQLiteJobRepositoryError("A durable-job transition cannot change job or tenant identity.")
        if changed.version != previous.version + 1:
            raise SQLiteJobRepositoryError("A durable-job transition must advance exactly one version.")
        if (
            event.job_id != changed.id
            or event.job_version != changed.version
            or event.from_status is not previous.status
            or event.to_status is not changed.status
        ):
            raise SQLiteJobRepositoryError("Transition evidence does not match the durable-job versions.")

    def _persist_transition_rows(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
    ) -> None:
        self._validate_transition(previous, changed, event)
        assignments = ", ".join(f"{column} = ?" for column in _JOB_COLUMNS[1:])
        values = _job_values(changed)[1:]
        cursor = self.connection.execute(
            f"UPDATE durable_jobs SET {assignments} WHERE tenant_id = ? AND id = ? AND version = ?",  # noqa: S608
            (*values, previous.tenant_id, previous.id, previous.version),
        )
        if cursor.rowcount != 1:
            raise SQLiteJobConflictError("Durable job changed before this transition could commit.")
        self.connection.execute(
            """
            INSERT INTO durable_job_transitions
                (job_id, job_version, from_status, to_status, actor_id, occurred_at, reason_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
        sequence_row = self.connection.execute(
            "SELECT COALESCE(MAX(event_sequence), 0) + 1 AS next_sequence "
            "FROM durable_job_lease_events WHERE job_id = ?",
            (lease.job_id,),
        ).fetchone()
        self.connection.execute(
            """
            INSERT INTO durable_job_lease_events
                (job_id, event_sequence, generation, action, owner_id, occurred_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lease.job_id,
                int(sequence_row["next_sequence"]),
                lease.generation,
                action,
                lease.owner_id,
                occurred_at,
                "" if action == "released" else lease.expires_at,
            ),
        )

    def claim_next(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        occurred_at: str,
        lease_expires_at: str,
    ) -> tuple[DurableJob, JobLease] | None:
        """Claim queued work or take over the oldest expired running job."""

        self._begin()
        try:
            row = self.connection.execute(
                """
                SELECT jobs.*,
                       COALESCE(
                           (SELECT MAX(events.generation)
                            FROM durable_job_lease_events events
                            WHERE events.job_id = jobs.id),
                           0
                       ) AS prior_lease_generation
                FROM durable_jobs jobs
                LEFT JOIN durable_job_leases leases ON leases.job_id = jobs.id
                WHERE jobs.tenant_id = ?
                  AND (
                    jobs.status = 'queued'
                    OR (jobs.status = 'retrying' AND (leases.job_id IS NULL OR leases.expires_at <= ?))
                    OR (jobs.status = 'running' AND (leases.job_id IS NULL OR leases.expires_at <= ?))
                  )
                ORDER BY
                    CASE jobs.status WHEN 'running' THEN 0 WHEN 'retrying' THEN 1 ELSE 2 END,
                    jobs.created_at,
                    jobs.id
                LIMIT 1
                """,
                (tenant_id, occurred_at, occurred_at),
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            previous = _decode_job(row)
            if previous.status in {JobStatus.QUEUED, JobStatus.RETRYING}:
                changed, event = previous.transition(
                    JobStatus.RUNNING,
                    actor_id=worker_id,
                    occurred_at=occurred_at,
                    reason_code="CLAIMED",
                )
                action = "claimed"
            else:
                changed, event = previous.reclaim(actor_id=worker_id, occurred_at=occurred_at)
                action = "taken_over"
            generation = int(row["prior_lease_generation"]) + 1
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
                INSERT INTO durable_job_leases
                    (job_id, tenant_id, owner_id, generation, acquired_at, renewed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    owner_id = excluded.owner_id,
                    generation = excluded.generation,
                    acquired_at = excluded.acquired_at,
                    renewed_at = excluded.renewed_at,
                    expires_at = excluded.expires_at
                """,
                (
                    lease.job_id,
                    lease.tenant_id,
                    lease.owner_id,
                    lease.generation,
                    lease.acquired_at,
                    lease.renewed_at,
                    lease.expires_at,
                ),
            )
            self._append_lease_event(lease, action=action, occurred_at=occurred_at)
            self.connection.commit()
            return changed, lease
        except (SQLiteJobConflictError, SQLiteJobRepositoryError):
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise SQLiteJobRepositoryError("Unable to claim durable job.") from exc

    def renew_lease(
        self,
        lease: JobLease,
        *,
        occurred_at: str,
        lease_expires_at: str,
    ) -> JobLease:
        """Extend an active lease only for its exact owner and generation."""

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
            raise SQLiteJobConflictError("Durable-job lease is expired or was not extended.")
        self._begin()
        try:
            cursor = self.connection.execute(
                """
                UPDATE durable_job_leases
                SET renewed_at = ?, expires_at = ?
                WHERE job_id = ? AND tenant_id = ? AND owner_id = ? AND generation = ?
                  AND expires_at > ?
                """,
                (
                    renewed.renewed_at,
                    renewed.expires_at,
                    renewed.job_id,
                    renewed.tenant_id,
                    renewed.owner_id,
                    renewed.generation,
                    occurred_at,
                ),
            )
            if cursor.rowcount != 1:
                raise SQLiteJobConflictError("Durable-job lease ownership changed or expired.")
            self._append_lease_event(renewed, action="renewed", occurred_at=occurred_at)
            self.connection.commit()
            return renewed
        except SQLiteJobConflictError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise SQLiteJobRepositoryError("Unable to renew durable-job lease.") from exc

    def persist_owned_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
        *,
        lease: JobLease,
        release_lease: bool,
    ) -> DurableJob:
        """Persist worker output only while its exact lease remains active."""

        self._validate_transition(previous, changed, event)
        self._begin()
        try:
            owned = self.connection.execute(
                """
                SELECT 1 FROM durable_job_leases
                WHERE job_id = ? AND tenant_id = ? AND owner_id = ? AND generation = ?
                  AND expires_at > ?
                """,
                (
                    lease.job_id,
                    lease.tenant_id,
                    lease.owner_id,
                    lease.generation,
                    event.occurred_at,
                ),
            ).fetchone()
            if owned is None or previous.id != lease.job_id or previous.tenant_id != lease.tenant_id:
                raise SQLiteJobConflictError("Durable-job lease ownership changed or expired.")
            self._persist_transition_rows(previous, changed, event)
            if release_lease:
                self.connection.execute(
                    "DELETE FROM durable_job_leases WHERE job_id = ? AND owner_id = ? AND generation = ?",
                    (lease.job_id, lease.owner_id, lease.generation),
                )
                self._append_lease_event(lease, action="released", occurred_at=event.occurred_at)
            self.connection.commit()
            return changed
        except SQLiteJobConflictError:
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise SQLiteJobConflictError("Durable-job leased transition conflicts with stored evidence.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise SQLiteJobRepositoryError("Unable to persist leased durable-job transition.") from exc

    def list_lease_events(self, *, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        if self.get(tenant_id=tenant_id, job_id=job_id) is None:
            return []
        rows = self.connection.execute(
            "SELECT * FROM durable_job_lease_events WHERE job_id = ? ORDER BY event_sequence",
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_transitions(self, *, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        if self.get(tenant_id=tenant_id, job_id=job_id) is None:
            return []
        rows = self.connection.execute(
            "SELECT * FROM durable_job_transitions WHERE job_id = ? ORDER BY job_version",
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]
