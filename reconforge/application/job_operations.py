"""Bounded operator projections over the existing durable-job engine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from reconforge.application.jobs import DurableJobNotFoundError, JobAuthorizationError
from reconforge.auth.policy import (
    CentralPolicyEngine,
    PolicyAuditSink,
    PolicyEvaluationContext,
    audit_policy_decision,
)
from reconforge.domain.jobs import ID_PATTERN, DurableJob, DurableJobQueueSnapshot, JobStatus


@dataclass(frozen=True)
class JobOperationsScope:
    tenant_id: str
    workspace_id: str
    entity_id: str
    organization_id: str = ""

    def __post_init__(self) -> None:
        # Reuse the lifecycle's canonical identifier admission.
        admitted = DurableJobQueueSnapshot(tenant_id=self.tenant_id, workspace_id=self.workspace_id,
                                           organization_id=self.organization_id, entity_id=self.entity_id)
        if (admitted.tenant_id, admitted.workspace_id, admitted.organization_id, admitted.entity_id) != (
                self.tenant_id, self.workspace_id, self.organization_id, self.entity_id):
            raise ValueError("Job operations scope must use canonical identifiers.")
        if not self.workspace_id or not self.entity_id:
            raise ValueError("Job operations require a complete workspace and entity lane.")

    def contains(self, job: DurableJob) -> bool:
        return (job.tenant_id, job.workspace_id, job.organization_id, job.entity_id) == (
            self.tenant_id, self.workspace_id, self.organization_id, self.entity_id)


class JobOperationsRepository(Protocol):
    def get(self, *, tenant_id: str, job_id: str) -> DurableJob | None: ...

    def list_jobs(self, *, tenant_id: str, workspace_id: str, organization_id: str, entity_id: str,
                  status: JobStatus | None, after_id: str, limit: int) -> list[DurableJob]: ...

    def list_transitions(self, *, tenant_id: str, job_id: str,
                         limit: int | None = None) -> list[dict[str, object]]: ...


def job_operator_record(job: DurableJob) -> dict[str, object]:
    """Closed operational projection: no keys, source rows or manifest paths."""
    return {"id": job.id, "version": job.version, "status": job.status.value,
            "tenant_id": job.tenant_id, "workspace_id": job.workspace_id,
            "organization_id": job.organization_id, "entity_id": job.entity_id,
            "completed_units": job.completed_units, "total_units": job.total_units,
            "retry_count": job.retry_count, "retry_ceiling": job.retry_ceiling,
            "safe_error_code": job.safe_error_code, "created_at": job.created_at,
            "updated_at": job.updated_at, "started_at": job.started_at,
            "completed_at": job.completed_at}


class JobOperationsService:
    def __init__(self, repository: JobOperationsRepository, *, audit_sink: PolicyAuditSink | None = None) -> None:
        self.repository = repository
        self.audit_sink = audit_sink

    def authorize(self, scope: JobOperationsScope, context: PolicyEvaluationContext, *,
                  permission: str = "ops.read", object_id: str = "lane", action: str = "read",
                  request_id: str = "") -> None:
        if (context.tenant_id, context.workspace_id, context.organization_id or "", context.entity_id) != (
                scope.tenant_id, scope.workspace_id, scope.organization_id, scope.entity_id):
            raise JobAuthorizationError("Job operations policy scope does not match execution lane.")
        bound = replace(context, object_type="durable_job", object_id=object_id, action=action)
        decision = CentralPolicyEngine().evaluate(bound, required_permission=permission,
                                                  enforce_sod=True, enforce_ownership=True)
        audit_policy_decision(decision, actor_id=context.user_id, required_permissions=frozenset({permission}),
                              surface=f"durable-job.operations.{action}", request_id=request_id,
                              principal_type=context.principal_type, context=bound, audit_sink=self.audit_sink)
        if not decision.allowed:
            raise JobAuthorizationError(decision.reason_code)

    def page(self, scope: JobOperationsScope, context: PolicyEvaluationContext, *, status: JobStatus | None = None,
             after_id: str = "", limit: int = 25, request_id: str = "") -> dict[str, object]:
        self.authorize(scope, context, request_id=request_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("Job page limit must be between 1 and 50.")
        if after_id and not ID_PATTERN.fullmatch(after_id):
            raise ValueError("Job page cursor is invalid.")
        jobs = self.repository.list_jobs(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id,
                                        organization_id=scope.organization_id, entity_id=scope.entity_id,
                                        status=status, after_id=after_id, limit=limit + 1)
        if any(not scope.contains(job) for job in jobs):
            raise JobAuthorizationError("Repository returned a job outside the selected lane.")
        visible = jobs[:limit]
        return {"records": [job_operator_record(job) for job in visible],
                "next_after_id": visible[-1].id if len(jobs) > limit else ""}

    def detail(self, scope: JobOperationsScope, context: PolicyEvaluationContext, *, job_id: str,
               request_id: str = "") -> dict[str, object]:
        self.authorize(scope, context, object_id=job_id, request_id=request_id)
        job = self.repository.get(tenant_id=scope.tenant_id, job_id=job_id)
        if job is None or not scope.contains(job):
            raise DurableJobNotFoundError("Durable job was not found in the selected lane.")
        events = self.repository.list_transitions(tenant_id=scope.tenant_id, job_id=job_id, limit=201)
        # The history is bounded; callers can see whether earlier transitions
        # require a retained database evidence export.
        fields = ("job_version", "from_status", "to_status", "actor_id", "occurred_at", "reason_code")
        return {"job": job_operator_record(job),
                "transitions": [{key: event[key] for key in fields} for event in events[-200:]],
                "history_truncated": len(events) > 200}
