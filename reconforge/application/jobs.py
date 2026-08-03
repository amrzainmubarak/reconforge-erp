"""Backend-neutral application service for durable jobs and checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reconforge.auth.policy import CentralPolicyEngine, PolicyDecision, PolicyEvaluationContext
from reconforge.domain.jobs import (
    DurableJob,
    DurableJobBackpressureError,
    JobLease,
    JobOutputManifest,
    JobPartitionEffect,
    JobStatus,
    JobTransition,
)
from reconforge.observability import ObservabilityRuntime


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


class BoundedDurableJobRepositoryProtocol(DurableJobRepositoryProtocol, Protocol):
    """Storage contract for an atomic execution-lane queue cap."""

    def create_or_get_bounded(
        self,
        job: DurableJob,
        *,
        actor_id: str,
        max_queued_jobs: int,
    ) -> tuple[DurableJob, bool]: ...


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

    def persist_owned_effect_transition(
        self,
        previous: DurableJob,
        changed: DurableJob,
        event: JobTransition,
        effect: JobPartitionEffect,
        *,
        lease: JobLease,
        release_lease: bool,
    ) -> DurableJob: ...

    def list_partition_effects(self, *, tenant_id: str, job_id: str) -> list[JobPartitionEffect]: ...


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


def _job_from_submission(submission: JobSubmission) -> DurableJob:
    return DurableJob.queued(
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


@dataclass(frozen=True)
class LeasedJob:
    """A job paired with the exact fencing token required for worker writes."""

    job: DurableJob
    lease: JobLease


class DurableJobApplicationService:
    """Coordinate job lifecycle while persistence owns atomic compare-and-swap."""

    def __init__(
        self,
        repository: DurableJobRepositoryProtocol,
        *,
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._repository = repository
        self._observability = observability or ObservabilityRuntime.disabled()

    def submit(self, submission: JobSubmission, *, actor_id: str) -> tuple[DurableJob, bool]:
        job = _job_from_submission(submission)
        attributes: dict[str, object] = {"job.type": "durable", "reconforge.operation": "submit"}
        with self._observability.span("reconforge.job.submit", attributes) as span:
            persisted, created = self._repository.create_or_get(job, actor_id=actor_id)
            result = "created" if created else "replayed"
            if span is not None:
                span.set_attribute("reconforge.result", result)
            self._observability.record_job(
                {**attributes, "job.status": persisted.status.value, "reconforge.result": result}
            )
            return persisted, created

    def submit_bounded(
        self,
        submission: JobSubmission,
        *,
        actor_id: str,
        max_queued_jobs: int,
    ) -> tuple[DurableJob, bool]:
        """Submit through a backend-atomic cap for one tenant/workspace/entity lane."""

        if isinstance(max_queued_jobs, bool) or not isinstance(max_queued_jobs, int) or max_queued_jobs < 1:
            raise ValueError("max_queued_jobs must be a positive integer")
        create_or_get_bounded = getattr(self._repository, "create_or_get_bounded", None)
        if create_or_get_bounded is None:
            raise DurableJobBackpressureError(
                "The configured durable-job backend does not support atomic queue bounds."
            )
        job = _job_from_submission(submission)
        attributes: dict[str, object] = {
            "job.type": "durable",
            "reconforge.operation": "submit_bounded",
            "job.queue_cap": max_queued_jobs,
        }
        with self._observability.span("reconforge.job.submit_bounded", attributes) as span:
            persisted, created = create_or_get_bounded(
                job,
                actor_id=actor_id,
                max_queued_jobs=max_queued_jobs,
            )
            result = "created" if created else "replayed"
            if span is not None:
                span.set_attribute("reconforge.result", result)
            self._observability.record_job(
                {**attributes, "job.status": persisted.status.value, "reconforge.result": result}
            )
            return persisted, created

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
        attributes: dict[str, object] = {
            "job.type": "durable",
            "job.status": to_status.value,
            "reconforge.operation": "transition",
        }
        with self._observability.span("reconforge.job.transition", attributes):
            persisted = self._repository.persist_transition(previous, changed, event)
            self._observability.record_job({**attributes, "reconforge.result": "persisted"})
            return persisted

    def _require_job(self, *, tenant_id: str, job_id: str) -> DurableJob:
        job = self._repository.get(tenant_id=tenant_id, job_id=job_id)
        if job is None:
            raise DurableJobNotFoundError("Durable job was not found in the requested tenant scope.")
        return job


class JobAuthorizationError(PermissionError):
    """Raised when a governed job mutation fails central policy evaluation."""


class GovernedDurableJobApplicationService:
    """Policy boundary for job mutations; the underlying lifecycle remains reusable."""

    def __init__(
        self,
        service: DurableJobApplicationService,
        *,
        policy_engine: CentralPolicyEngine | None = None,
    ) -> None:
        self._service = service
        self._policy = policy_engine or CentralPolicyEngine()

    def submit(
        self,
        submission: JobSubmission,
        *,
        actor_id: str,
        policy_context: PolicyEvaluationContext,
        required_permission: str,
    ) -> tuple[DurableJob, bool]:
        self._authorize(
            policy_context,
            actor_id=actor_id,
            required_permission=required_permission,
            tenant_id=submission.tenant_id,
            workspace_id=submission.workspace_id,
            object_id=submission.job_id,
            action="submit",
        )
        return self._service.submit(submission, actor_id=actor_id)

    def submit_bounded(
        self,
        submission: JobSubmission,
        *,
        actor_id: str,
        max_queued_jobs: int,
        policy_context: PolicyEvaluationContext,
        required_permission: str,
    ) -> tuple[DurableJob, bool]:
        self._authorize(
            policy_context,
            actor_id=actor_id,
            required_permission=required_permission,
            tenant_id=submission.tenant_id,
            workspace_id=submission.workspace_id,
            object_id=submission.job_id,
            action="submit_bounded",
        )
        return self._service.submit_bounded(
            submission,
            actor_id=actor_id,
            max_queued_jobs=max_queued_jobs,
        )

    def cancel(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        job_id: str,
        actor_id: str,
        occurred_at: str,
        policy_context: PolicyEvaluationContext,
        required_permission: str,
    ) -> DurableJob:
        self._authorize(
            policy_context,
            actor_id=actor_id,
            required_permission=required_permission,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            object_id=job_id,
            action="cancel",
        )
        return self._service.cancel(
            tenant_id=tenant_id, job_id=job_id, actor_id=actor_id, occurred_at=occurred_at
        )

    def _authorize(
        self,
        context: PolicyEvaluationContext,
        *,
        actor_id: str,
        required_permission: str,
        tenant_id: str,
        workspace_id: str,
        object_id: str,
        action: str,
    ) -> PolicyDecision:
        if actor_id != context.user_id:
            raise JobAuthorizationError("job actor does not match policy identity")
        decision = self._policy.evaluate(
            context,
            required_permission=required_permission,
            enforce_sod=True,
            enforce_ownership=True,
        )
        if not decision.allowed:
            raise JobAuthorizationError(f"job policy denied: {decision.reason_code}")
        if context.tenant_id != tenant_id or context.workspace_id != workspace_id:
            raise JobAuthorizationError("job policy scope does not match mutation scope")
        return decision


class DurableJobWorkerService:
    """Crash-safe worker lifecycle using expiring, generation-fenced leases."""

    def __init__(
        self,
        repository: DurableJobWorkerRepositoryProtocol,
        *,
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._repository = repository
        self._observability = observability or ObservabilityRuntime.disabled()

    def claim(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        occurred_at: str,
        lease_expires_at: str,
    ) -> LeasedJob | None:
        attributes: dict[str, object] = {"job.type": "durable", "reconforge.operation": "claim"}
        with self._observability.span("reconforge.job.claim", attributes) as span:
            claimed = self._repository.claim_next(
                tenant_id=tenant_id,
                worker_id=worker_id,
                occurred_at=occurred_at,
                lease_expires_at=lease_expires_at,
            )
            result = "empty" if claimed is None else "claimed"
            if span is not None:
                span.set_attribute("reconforge.result", result)
            self._observability.record_job({**attributes, "reconforge.result": result})
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

    def completed_effects(self, leased_job: LeasedJob) -> list[JobPartitionEffect]:
        """Return committed effects so a resumed worker can skip them."""

        return self._repository.list_partition_effects(
            tenant_id=leased_job.job.tenant_id,
            job_id=leased_job.job.id,
        )

    def commit_partition(
        self,
        leased_job: LeasedJob,
        *,
        partition_key: str,
        ordinal: int,
        completed_units: int,
        input_digest: str,
        output_digest: str,
        effect_reference: str,
        occurred_at: str,
    ) -> LeasedJob:
        """Atomically commit one non-final effect and its checkpoint."""

        changed, event = leased_job.job.checkpoint(
            actor_id=leased_job.lease.owner_id,
            occurred_at=occurred_at,
            completed_units=completed_units,
            checkpoint_digest=output_digest,
        )
        effect = JobPartitionEffect(
            job_id=leased_job.job.id,
            partition_key=partition_key,
            ordinal=ordinal,
            completed_units=completed_units,
            input_digest=input_digest,
            output_digest=output_digest,
            effect_reference=effect_reference,
            committed_at=occurred_at,
        )
        persisted = self._repository.persist_owned_effect_transition(
            leased_job.job,
            changed,
            event,
            effect,
            lease=leased_job.lease,
            release_lease=False,
        )
        return LeasedJob(persisted, leased_job.lease)

    def complete_partition(
        self,
        leased_job: LeasedJob,
        *,
        partition_key: str,
        ordinal: int,
        input_digest: str,
        output_digest: str,
        effect_reference: str,
        occurred_at: str,
        output_manifest: JobOutputManifest,
    ) -> DurableJob:
        """Atomically commit the final effect, completion, manifest, and lease release."""

        changed, event = leased_job.job.transition(
            JobStatus.COMPLETED,
            actor_id=leased_job.lease.owner_id,
            occurred_at=occurred_at,
            reason_code="FINISHED",
            completed_units=leased_job.job.total_units,
            output_manifest=output_manifest,
        )
        effect = JobPartitionEffect(
            job_id=leased_job.job.id,
            partition_key=partition_key,
            ordinal=ordinal,
            completed_units=leased_job.job.total_units,
            input_digest=input_digest,
            output_digest=output_digest,
            effect_reference=effect_reference,
            committed_at=occurred_at,
        )
        return self._repository.persist_owned_effect_transition(
            leased_job.job,
            changed,
            event,
            effect,
            lease=leased_job.lease,
            release_lease=True,
        )

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
