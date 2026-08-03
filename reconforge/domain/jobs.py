"""Pure, versioned durable-job invariants with no persistence dependency."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

JOB_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$")


class JobInvariantError(ValueError):
    """Raised when a job would enter an invalid or unsafe state."""


class DurableJobBackpressureError(RuntimeError):
    """Raised when a new job would exceed its bounded execution-lane queue."""


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.PAUSED,
            JobStatus.RETRYING,
            JobStatus.FAILED,
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.PAUSED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.RETRYING: frozenset({JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def _identifier(value: str, field: str, *, optional: bool = False) -> str:
    if not isinstance(value, str):
        raise JobInvariantError(f"{field} must be text.")
    normalized = value.strip()
    if optional and not normalized:
        return ""
    if not ID_PATTERN.fullmatch(normalized):
        raise JobInvariantError(f"{field} has an invalid format.")
    return normalized


def _digest(value: str, field: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise JobInvariantError(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _utc_timestamp(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise JobInvariantError(f"{field} must be a canonical UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise JobInvariantError(f"{field} must be a canonical UTC timestamp.") from exc
    if parsed.tzinfo != UTC or parsed.microsecond:
        raise JobInvariantError(f"{field} must be a whole-second canonical UTC timestamp.")
    canonical = parsed.isoformat().replace("+00:00", "Z")
    if canonical != value:
        raise JobInvariantError(f"{field} must be a canonical UTC timestamp.")
    return value


@dataclass(frozen=True)
class JobOutputManifest:
    """Digest-addressed output produced only by a completed job."""

    schema_version: int
    digest: str
    reference: str

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise JobInvariantError("output manifest schema_version must be positive.")
        object.__setattr__(self, "digest", _digest(self.digest, "output manifest digest"))
        object.__setattr__(self, "reference", _identifier(self.reference, "output manifest reference"))


@dataclass(frozen=True)
class JobTransition:
    """Append-only transition evidence persisted with the changed job."""

    job_id: str
    job_version: int
    from_status: JobStatus
    to_status: JobStatus
    actor_id: str
    occurred_at: str
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _identifier(self.job_id, "job_id"))
        if isinstance(self.job_version, bool) or self.job_version < 1:
            raise JobInvariantError("job_version must be positive.")
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        object.__setattr__(self, "occurred_at", _utc_timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "reason_code", _identifier(self.reason_code, "reason_code"))


@dataclass(frozen=True)
class JobLease:
    """Time-bounded ownership token used to reject stale workers."""

    job_id: str
    tenant_id: str
    owner_id: str
    generation: int
    acquired_at: str
    renewed_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for field in ("job_id", "tenant_id", "owner_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        if isinstance(self.generation, bool) or self.generation < 1:
            raise JobInvariantError("lease generation must be positive.")
        for field in ("acquired_at", "renewed_at", "expires_at"):
            object.__setattr__(self, field, _utc_timestamp(getattr(self, field), field))
        if self.renewed_at < self.acquired_at:
            raise JobInvariantError("lease renewal cannot precede acquisition.")
        if self.expires_at <= self.renewed_at:
            raise JobInvariantError("lease expiry must follow its latest renewal.")


@dataclass(frozen=True)
class JobPartitionEffect:
    """One immutable, digest-addressed workload effect committed with progress."""

    job_id: str
    partition_key: str
    ordinal: int
    completed_units: int
    input_digest: str
    output_digest: str
    effect_reference: str
    committed_at: str

    def __post_init__(self) -> None:
        for field in ("job_id", "partition_key", "effect_reference"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        if isinstance(self.ordinal, bool) or self.ordinal < 1:
            raise JobInvariantError("partition ordinal must be positive.")
        if isinstance(self.completed_units, bool) or self.completed_units < 1:
            raise JobInvariantError("partition completed_units must be positive integer units.")
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "partition input_digest"))
        object.__setattr__(self, "output_digest", _digest(self.output_digest, "partition output_digest"))
        object.__setattr__(self, "committed_at", _utc_timestamp(self.committed_at, "committed_at"))


@dataclass(frozen=True)
class DurableJob:
    """Backend-neutral durable-job aggregate."""

    id: str
    version: int
    status: JobStatus
    idempotency_scope: str
    idempotency_key: str
    tenant_id: str
    workspace_id: str
    entity_id: str
    input_digest: str
    config_digest: str
    worker_version: str
    completed_units: int
    total_units: int
    checkpoint_digest: str
    retry_count: int
    retry_ceiling: int
    safe_error_code: str
    created_at: str
    updated_at: str
    started_at: str
    completed_at: str
    output_manifest: JobOutputManifest | None
    schema_version: int = JOB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != JOB_SCHEMA_VERSION:
            raise JobInvariantError("Unsupported durable-job schema version.")
        for field in ("id", "idempotency_scope", "idempotency_key", "tenant_id", "workspace_id", "worker_version"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, "entity_id", _identifier(self.entity_id, "entity_id", optional=True))
        object.__setattr__(self, "input_digest", _digest(self.input_digest, "input_digest"))
        object.__setattr__(self, "config_digest", _digest(self.config_digest, "config_digest"))
        object.__setattr__(
            self, "checkpoint_digest", _digest(self.checkpoint_digest, "checkpoint_digest", optional=True)
        )
        object.__setattr__(self, "created_at", _utc_timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _utc_timestamp(self.updated_at, "updated_at"))
        for field in ("started_at", "completed_at"):
            value = getattr(self, field)
            if value:
                object.__setattr__(self, field, _utc_timestamp(value, field))
        if isinstance(self.version, bool) or self.version < 1:
            raise JobInvariantError("version must be positive.")
        if isinstance(self.completed_units, bool) or isinstance(self.total_units, bool):
            raise JobInvariantError("job progress must use integer units.")
        if self.completed_units < 0 or self.total_units < 0 or self.completed_units > self.total_units:
            raise JobInvariantError("job progress is outside its declared total.")
        if isinstance(self.retry_count, bool) or isinstance(self.retry_ceiling, bool):
            raise JobInvariantError("retry counts must use integer units.")
        if self.retry_count < 0 or self.retry_ceiling < 0 or self.retry_count > self.retry_ceiling:
            raise JobInvariantError("retry count is outside its declared ceiling.")
        if self.safe_error_code and not SAFE_CODE_PATTERN.fullmatch(self.safe_error_code):
            raise JobInvariantError("safe_error_code has an invalid format.")
        if self.updated_at < self.created_at:
            raise JobInvariantError("updated_at cannot precede created_at.")
        if self.status is JobStatus.COMPLETED:
            if self.output_manifest is None or self.completed_units != self.total_units or not self.completed_at:
                raise JobInvariantError("completed jobs require full progress, completion time, and output manifest.")
        elif self.output_manifest is not None:
            raise JobInvariantError("only completed jobs may publish an output manifest.")
        elif self.completed_at:
            raise JobInvariantError("only completed jobs may carry completed_at.")
        if self.status is JobStatus.FAILED and not self.safe_error_code:
            raise JobInvariantError("failed jobs require a safe error code.")
        if self.status is not JobStatus.FAILED and self.safe_error_code:
            raise JobInvariantError("only failed jobs may carry a safe error code.")
        if (
            self.status
            in {
                JobStatus.RUNNING,
                JobStatus.PAUSED,
                JobStatus.RETRYING,
                JobStatus.FAILED,
                JobStatus.COMPLETED,
            }
            and not self.started_at
        ):
            raise JobInvariantError("started jobs require started_at.")

    @classmethod
    def queued(
        cls,
        *,
        job_id: str,
        idempotency_scope: str,
        idempotency_key: str,
        tenant_id: str,
        workspace_id: str,
        entity_id: str = "",
        input_digest: str,
        config_digest: str,
        worker_version: str,
        total_units: int,
        retry_ceiling: int,
        created_at: str,
    ) -> DurableJob:
        return cls(
            id=job_id,
            version=1,
            status=JobStatus.QUEUED,
            idempotency_scope=idempotency_scope,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            entity_id=entity_id,
            input_digest=input_digest,
            config_digest=config_digest,
            worker_version=worker_version,
            completed_units=0,
            total_units=total_units,
            checkpoint_digest="",
            retry_count=0,
            retry_ceiling=retry_ceiling,
            safe_error_code="",
            created_at=created_at,
            updated_at=created_at,
            started_at="",
            completed_at="",
            output_manifest=None,
        )

    def transition(
        self,
        to_status: JobStatus,
        *,
        actor_id: str,
        occurred_at: str,
        reason_code: str,
        completed_units: int | None = None,
        checkpoint_digest: str | None = None,
        safe_error_code: str = "",
        output_manifest: JobOutputManifest | None = None,
    ) -> tuple[DurableJob, JobTransition]:
        if to_status not in ALLOWED_TRANSITIONS[self.status]:
            raise JobInvariantError(f"Transition {self.status.value}->{to_status.value} is not allowed.")
        actor = _identifier(actor_id, "actor_id")
        reason = _identifier(reason_code, "reason_code")
        timestamp = _utc_timestamp(occurred_at, "occurred_at")
        if timestamp < self.updated_at:
            raise JobInvariantError("transition time cannot precede the current job version.")
        next_retry = self.retry_count + (1 if to_status is JobStatus.RETRYING else 0)
        if next_retry > self.retry_ceiling:
            raise JobInvariantError("retry ceiling has been exhausted.")
        next_completed = self.completed_units if completed_units is None else completed_units
        next_checkpoint = self.checkpoint_digest if checkpoint_digest is None else checkpoint_digest
        next_started = self.started_at
        if to_status is JobStatus.RUNNING and not next_started:
            next_started = timestamp
        next_completed_at = timestamp if to_status is JobStatus.COMPLETED else ""
        next_error = safe_error_code if to_status is JobStatus.FAILED else ""
        changed = replace(
            self,
            version=self.version + 1,
            status=to_status,
            completed_units=next_completed,
            checkpoint_digest=next_checkpoint,
            retry_count=next_retry,
            safe_error_code=next_error,
            updated_at=timestamp,
            started_at=next_started,
            completed_at=next_completed_at,
            output_manifest=output_manifest,
        )
        event = JobTransition(
            job_id=self.id,
            job_version=changed.version,
            from_status=self.status,
            to_status=to_status,
            actor_id=actor,
            occurred_at=timestamp,
            reason_code=reason,
        )
        return changed, event

    def checkpoint(
        self,
        *,
        actor_id: str,
        occurred_at: str,
        completed_units: int,
        checkpoint_digest: str,
    ) -> tuple[DurableJob, JobTransition]:
        """Advance resumable progress without changing the running state."""

        if self.status is not JobStatus.RUNNING:
            raise JobInvariantError("Only running jobs may persist a checkpoint.")
        if completed_units < self.completed_units:
            raise JobInvariantError("checkpoint progress cannot move backwards.")
        if completed_units >= self.total_units:
            raise JobInvariantError("a checkpoint must precede full completion.")
        actor = _identifier(actor_id, "actor_id")
        timestamp = _utc_timestamp(occurred_at, "occurred_at")
        if timestamp < self.updated_at:
            raise JobInvariantError("transition time cannot precede the current job version.")
        digest = _digest(checkpoint_digest, "checkpoint_digest")
        changed = replace(
            self,
            version=self.version + 1,
            completed_units=completed_units,
            checkpoint_digest=digest,
            updated_at=timestamp,
        )
        return changed, JobTransition(
            job_id=self.id,
            job_version=changed.version,
            from_status=self.status,
            to_status=self.status,
            actor_id=actor,
            occurred_at=timestamp,
            reason_code="CHECKPOINTED",
        )

    def reclaim(
        self,
        *,
        actor_id: str,
        occurred_at: str,
    ) -> tuple[DurableJob, JobTransition]:
        """Record deterministic takeover of a running job after lease expiry."""

        if self.status is not JobStatus.RUNNING:
            raise JobInvariantError("Only running jobs may be reclaimed.")
        actor = _identifier(actor_id, "actor_id")
        timestamp = _utc_timestamp(occurred_at, "occurred_at")
        if timestamp < self.updated_at:
            raise JobInvariantError("transition time cannot precede the current job version.")
        changed = replace(self, version=self.version + 1, updated_at=timestamp)
        return changed, JobTransition(
            job_id=self.id,
            job_version=changed.version,
            from_status=self.status,
            to_status=self.status,
            actor_id=actor,
            occurred_at=timestamp,
            reason_code="LEASE_TAKEOVER",
        )
