"""Scoped durable-job operator API; lifecycle writes retain original evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import _server_policy_audit_sink, get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.api.routes.operations import _server_job_policy_context
from reconforge.api.server_identity import (
    get_postgres_identity_factory,
    request_execution_scope,
    server_identity_enabled,
)
from reconforge.application.job_operations import JobOperationsScope, JobOperationsService, job_operator_record
from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobNotFoundError,
    DurableJobVersionConflictError,
    GovernedDurableJobApplicationService,
    JobAuthorizationError,
)
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.auth.service import LocalAuthService
from reconforge.domain.jobs import JobInvariantError, JobStatus
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository, PostgresJobConflictError
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository, SQLiteJobConflictError

router = APIRouter(prefix="/ops/durable-jobs", tags=["durable-job-operations"])
JobRead = Annotated[LocalUser, Depends(require_permission("ops.read"))]
JobManage = Annotated[LocalUser, Depends(require_permission("jobs.manage"))]
LocalDb = Annotated[sqlite3.Connection | None, Depends(get_local_db)]
T = TypeVar("T")


class JobOperatorCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1, le=9_000_000_000_000_000_000)


def selected_job_scope(
    request: Request,
    tenant_id: str = Query(default="local", min_length=1, max_length=160),
    workspace_id: str = Query(default="", max_length=160),
    organization_id: str = Query(default="", max_length=160),
    entity_id: str = Query(default="", max_length=160),
) -> JobOperationsScope:
    try:
        if server_identity_enabled(request):
            execution = request_execution_scope(request)
            if execution.legal_entity_id is None:
                raise APIError(status_code=400, code="entity_scope_required", message="Job operations require an entity lane.")
            # Never silently override explicit query scope with a different
            # header lane. Defaults remain compatible with the header profile.
            for name, supplied, selected in (
                ("tenant_id", tenant_id, execution.tenant_id),
                ("workspace_id", workspace_id, execution.workspace_id),
                ("organization_id", organization_id, execution.organization_id or ""),
                ("entity_id", entity_id, execution.legal_entity_id),
            ):
                if name in request.query_params and supplied != selected:
                    raise APIError(status_code=403, code="job_scope_denied", message="Job scope does not match authorized execution lane.")
            return JobOperationsScope(execution.tenant_id, execution.workspace_id,
                                      execution.legal_entity_id, execution.organization_id or "")
        if getattr(request.app.state, "tenant_db_router", None):
            routed_tenant = request.headers.get("x-reconforge-tenant", "local")
            if tenant_id != routed_tenant:
                raise APIError(status_code=403, code="job_scope_denied", message="Job tenant does not match database lane.")
        return JobOperationsScope(tenant_id, workspace_id, entity_id, organization_id)
    except APIError:
        raise
    except (JobInvariantError, ValueError) as exc:
        raise APIError(status_code=400, code="job_scope_invalid", message="A valid workspace and entity lane is required.") from exc


Scope = Annotated[JobOperationsScope, Depends(selected_job_scope)]
JobOperation = Callable[[JobOperationsService, GovernedDurableJobApplicationService, PolicyEvaluationContext], T]


def _execute(request: Request, connection: sqlite3.Connection | None, user: LocalUser,
             scope: JobOperationsScope, operation: JobOperation[T], *, mutation: bool = False) -> T:
    try:
        if server_identity_enabled(request):
            principal, context = _server_job_policy_context(request, tenant_id=scope.tenant_id,
                                                           workspace_id=scope.workspace_id,
                                                           organization_id=scope.organization_id or None,
                                                           entity_id=scope.entity_id)
            if mutation and principal.principal_type != "user":
                raise APIError(status_code=403, code="human_principal_required", message="Job operator actions require a human session.")
            if mutation and not principal.step_up_active:
                raise APIError(status_code=403, code="step_up_required", message="Recent reauthentication is required.")
            factory = get_postgres_identity_factory(request)
            if factory is None:
                raise APIError(status_code=503, code="job_operations_unavailable", message="Job operations are unavailable.")
            audit = _server_policy_audit_sink(request, actor_id=user.id)
            with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id,
                                                             organization_id=scope.organization_id or None,
                                                             legal_entity_id=scope.entity_id) as pg:
                repository = PostgresDurableJobRepository(pg)
                return operation(JobOperationsService(repository, audit_sink=audit),
                                 GovernedDurableJobApplicationService(DurableJobApplicationService(repository), audit_sink=audit), context)
        if connection is None:
            raise APIError(status_code=503, code="job_operations_unavailable", message="Job operations are unavailable.")
        context = PolicyEvaluationContext(user_id=user.id, username=user.username,
                                          user_permissions=LocalAuthService(connection).roles.user_permissions(user.username),
                                          tenant_id=scope.tenant_id, workspace_id=scope.workspace_id,
                                          organization_id=scope.organization_id or None, entity_id=scope.entity_id,
                                          authorized_tenant_ids=frozenset({scope.tenant_id}),
                                          authorized_workspace_ids=frozenset({scope.workspace_id}),
                                          authorized_organization_ids=frozenset({scope.organization_id}) if scope.organization_id else frozenset(),
                                          authorized_entity_ids=frozenset({scope.entity_id}))
        local_repository = SQLiteDurableJobRepository(connection)
        return operation(JobOperationsService(local_repository),
                         GovernedDurableJobApplicationService(DurableJobApplicationService(local_repository)), context)
    except APIError:
        raise
    except DurableJobNotFoundError as exc:
        raise APIError(status_code=404, code="job_not_found", message="Job not found in the selected lane.") from exc
    except JobAuthorizationError as exc:
        raise APIError(status_code=403, code="job_scope_denied", message="Job operation is not authorized.") from exc
    except (DurableJobVersionConflictError, SQLiteJobConflictError, PostgresJobConflictError) as exc:
        raise APIError(status_code=409, code="job_version_conflict", message="Job changed or is actively leased; refresh before acting.") from exc
    except (JobInvariantError, ValueError) as exc:
        raise APIError(status_code=409, code="job_transition_invalid", message="Job does not permit this operator transition.") from exc
    except Exception as exc:
        raise APIError(status_code=503, code="job_operations_unavailable", message="Job operations are temporarily unavailable.") from exc


@router.get("")
def job_page(request: Request, user: JobRead, connection: LocalDb, scope: Scope,
             status: JobStatus | None = None, after_id: str = Query(default="", max_length=160),
             limit: int = Query(default=25, ge=1, le=50)) -> dict[str, object]:
    return _execute(request, connection, user, scope,
                    lambda reads, _writes, context: reads.page(scope, context, status=status,
                                                               after_id=after_id, limit=limit,
                                                               request_id=str(getattr(request.state, "request_id", ""))))


@router.get("/{job_id}")
def job_detail(job_id: str, request: Request, user: JobRead, connection: LocalDb, scope: Scope) -> dict[str, object]:
    return _execute(request, connection, user, scope,
                    lambda reads, _writes, context: reads.detail(scope, context, job_id=job_id,
                                                                 request_id=str(getattr(request.state, "request_id", ""))))


def _command(action: str, job_id: str, command: JobOperatorCommand, request: Request,
             user: LocalUser, connection: sqlite3.Connection | None, scope: JobOperationsScope) -> dict[str, object]:
    def apply(reads: JobOperationsService, writes: GovernedDurableJobApplicationService,
              context: PolicyEvaluationContext) -> dict[str, object]:
        # Exact lane admission precedes writes and conceals sibling metadata.
        reads.authorize(scope, context, permission="jobs.manage", object_id=job_id, action=action,
                        request_id=str(getattr(request.state, "request_id", "")))
        stored = reads.repository.get(tenant_id=scope.tenant_id, job_id=job_id)
        if stored is None or not scope.contains(stored):
            raise DurableJobNotFoundError("Job not found in the selected lane.")
        operation = writes.cancel if action == "cancel" else writes.requeue
        changed = operation(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id,
                            organization_id=scope.organization_id or None, entity_id=scope.entity_id,
                            job_id=job_id, actor_id=user.id, expected_version=command.expected_version,
                            occurred_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                            policy_context=context, required_permission="jobs.manage",
                            request_id=str(getattr(request.state, "request_id", "")))
        return {"job": job_operator_record(changed)}
    return _execute(request, connection, user, scope, apply, mutation=True)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, command: JobOperatorCommand, request: Request,
               user: JobManage, connection: LocalDb, scope: Scope) -> dict[str, object]:
    return _command("cancel", job_id, command, request, user, connection, scope)


@router.post("/{job_id}/requeue")
def requeue_job(job_id: str, command: JobOperatorCommand, request: Request,
                user: JobManage, connection: LocalDb, scope: Scope) -> dict[str, object]:
    return _command("requeue", job_id, command, request, user, connection, scope)
