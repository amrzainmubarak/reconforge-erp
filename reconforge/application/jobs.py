"""Backend-neutral application service for durable jobs and checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reconforge.domain.jobs import (
    DurableJob,
    JobLease,
    JobOutputManifest,
    JobStatus,
    JobTransition,
)


class DurableJobNotFoundError(LookupError):
    """Raised without disclosing another tenant's job existence."""


class DurableJobRepositoryProtocol(Protocol):
    """Atomic storage contract required by the durable-job application service."""

    def create_or_get(self, job: DurableJob, *, actor_id: str) -> tuple[DurableJob, bool]: ...

    def get(self, *, tenant_id: str, job_id: str) -> DurableJob | None: ...

    def persist_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
    ) -> DurableJob: ...


class DurableJobWorkerRepositoryProtocol(DurableJobRepositoryProtocol, Protocol):
    """Lease and fencing operations required by a crash-safe worker."""

    def claim_next(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        occurred_at: str,
        lease_expires_at: str,
    ) -> tuple[DurableJob, JobLease] | None: ...

    def renew_lease(
        self,
        lease: JobLease,
        *,
        occurred_at: str,
        lease_expires_at: str,
    ) -> JobLease: ...

    def persist_owned_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
        *,
        lease: JobLease,
        release_lease: bool,
    ) -> DurableJob: ...


@dataclass(frozen=True)
class JobSubmission:
    """Validated source data for one initial queued job."""

    job_id: str
    idempotency_scope: str
    idempotency_key: str
    tenant_id: str
    workspace_id: str
    entity_id: str
    input_digest: str
    config_digest: str
    worker_version: str
    total_units: int
    retry_ceiling: int
    created_at: str


@dataclass(frozen=True)
class LeasedJob:
    """A job paired with the exact fencing token required for worker writes."""

    job: DurableJob
    lease: JobLease


class DurableJobApplicationService:
    """Coordinate job lifecycle while persistence owns atomic compare-and-swap."""

    def __init__(self, repository: DurableJobRepositoryProtocol) -> None:
        self._repository = repository

    def submit(self, submission: JobSubmission, *, actor_id: str) -> tuple[DurableJob, bool]:
        job = DurableJob.queued(
            job_id=submission.job_id,
            idempotency_scope=submission.idempotency_scope,
            idempotency_key=submission.idempotency_key,
            tenant_id=submission.tenant_id,
            workspace_id=submission.workspace_id,
            entity_id=submission.entity_id,
            input_digest=submission.input_digest,
            config_digest=submission.config_digest,
            worker_version=submission.worker_version,
            total_units=submission.total_units,
            retry_ceiling=submission.retry_ceiling,
            created_at=submission.created_at,
        )
        return self._repository.create_or_get(job, actor_id=actor_id)

    def requeue(self, *, tenant_id: str, job_id: str, actor_id: str, occurred_at: str) -> DurableJob:
        return self._transition(
            tenant_id=tenant_id,
            job_id=job_id,
            to_status=JobStatus.QUEUED,
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason_code="REQUEUED",
        )

    def cancel(self, *, tenant_id: str, job_id: str, actor_id: str, occurred_at: str) -> DurableJob:
        return self._transition(
            tenant_id=tenant_id,
            job_id=job_id,
            to_status=JobStatus.CANCELLED,
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason_code="CANCELLED",
        )

    def _transition(
        self,
        *,
        tenant_id: str,
        job_id: str,
        to_status: JobStatus,
        actor_id: str,
        occurred_at: str,
        reason_code: str,
    ) -> DurableJob:
        previous = self._require_job(tenant_id=tenant_id, job_id=job_id)
        changed, event = previous.transition(
            to_status,
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason_code=reason_code,
        )
        return self._repository.persist_transition(previous, changed, event)

    def _require_job(self, *, tenant_id: str, job_id: str) -> DurableJob:
        job = self._repository.get(tenant_id=tenant_id, job_id=job_id)
        if job is None:
            raise DurableJobNotFoundError("Durable job was not found in the requested tenant scope.")
        return job


class DurableJobWorkerService:
    """Crash-safe worker lifecycle using expiring, generation-fenced leases."""

    def __init__(self, repository: DurableJobWorkerRepositoryProtocol) -> None:
        self._repository = repository

    def claim(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        occurred_at: str,
        lease_expires_at: str,
    ) -> LeasedJob | None:
        claimed = self._repository.claim_next(
            tenant_id=tenant_id,
            worker_id=worker_id,
            occurred_at=occurred_at,
            lease_expires_at=lease_expires_at,
        )
        return None if claimed is None else LeasedJob(*claimed)

    def heartbeat(
        self,
        leased_job: LeasedJob,
        *,
        occurred_at: str,
        lease_expires_at: str,
    ) -> LeasedJob:
        lease = self._repository.renew_lease(
            leased_job.lease,
            occurred_at=occurred_at,
            lease_expires_at=lease_expires_at,
        )
        return LeasedJob(leased_job.job, lease)

    def checkpoint(
        self,
        leased_job: LeasedJob,
        *,
        occurred_at: str,
        completed_units: int,
        checkpoint_digest: str,
    ) -> LeasedJob:
        changed, event = leased_job.job.checkpoint(
            actor_id=leased_job.lease.owner_id,
            occurred_at=occurred_at,
            completed_units=completed_units,
            checkpoint_digest=checkpoint_digest,
        )
        persisted = self._repository.persist_owned_transition(
            leased_job.job,
            changed,
            event,
            lease=leased_job.lease,
            release_lease=False,
        )
        return LeasedJob(persisted, leased_job.lease)

    def complete(
        self,
        leased_job: LeasedJob,
        *,
        occurred_at: str,
        output_manifest: JobOutputManifest,
    ) -> DurableJob:
        changed, event = leased_job.job.transition(
            JobStatus.COMPLETED,
            actor_id=leased_job.lease.owner_id,
            occurred_at=occurred_at,
            reason_code="FINISHED",
            completed_units=leased_job.job.total_units,
            output_manifest=output_manifest,
        )
        return self._repository.persist_owned_transition(
            leased_job.job,
            changed,
            event,
            lease=leased_job.lease,
            release_lease=True,
        )

    def schedule_retry(self, leased_job: LeasedJob, *, occurred_at: str) -> DurableJob:
        return self._finish_with_status(
            leased_job,
            to_status=JobStatus.RETRYING,
            occurred_at=occurred_at,
            reason_code="TRANSIENT_FAILURE",
        )

    def fail(
        self,
        leased_job: LeasedJob,
        *,
        occurred_at: str,
        safe_error_code: str,
    ) -> DurableJob:
        return self._finish_with_status(
            leased_job,
            to_status=JobStatus.FAILED,
            occurred_at=occurred_at,
            reason_code="TERMINAL_FAILURE",
            safe_error_code=safe_error_code,
        )

    def pause(self, leased_job: LeasedJob, *, occurred_at: str) -> DurableJob:
        return self._finish_with_status(
            leased_job,
            to_status=JobStatus.PAUSED,
            occurred_at=occurred_at,
            reason_code="OPERATOR_PAUSE",
        )

    def cancel(self, leased_job: LeasedJob, *, occurred_at: str) -> DurableJob:
        return self._finish_with_status(
            leased_job,
            to_status=JobStatus.CANCELLED,
            occurred_at=occurred_at,
            reason_code="CANCELLED",
        )

    def _finish_with_status(
        self,
        leased_job: LeasedJob,
        *,
        to_status: JobStatus,
        occurred_at: str,
        reason_code: str,
        safe_error_code: str = "",
    ) -> DurableJob:
        changed, event = leased_job.job.transition(
            to_status,
            actor_id=leased_job.lease.owner_id,
            occurred_at=occurred_at,
            reason_code=reason_code,
            safe_error_code=safe_error_code,
        )
        return self._repository.persist_owned_transition(
            leased_job.job,
            changed,
            event,
            lease=leased_job.lease,
            release_lease=True,
        )
