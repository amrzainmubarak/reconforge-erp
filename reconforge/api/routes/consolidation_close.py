"""Read-only API drill-down for the local consolidation-close lifecycle."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_close import (
    execute_postgres_consolidation_close,
    server_consolidation_close_enabled,
)
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_consolidation_close import PostgresConsolidationCloseRepository
from reconforge.infrastructure.sqlite_consolidation_close import SQLiteConsolidationCloseRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/consolidation-close", tags=["consolidation-close"])
ConsolidationRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
ConsolidationCertify = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]
ConsolidationReview = Annotated[LocalUser, Depends(require_permission("finance_core.validate"))]


class CertificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=1000)


def _repository(connection: sqlite3.Connection | None) -> SQLiteConsolidationCloseRepository:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    return SQLiteConsolidationCloseRepository(connection)


def _error(code: str, exc: Exception) -> APIError:
    return APIError(status_code=400, code=code, message=str(exc))


def _server_scope(request: Request, requested_workspace: str) -> RequestExecutionScope:
    """Resolve the authenticated hierarchy and reject query/header mismatches."""

    scope = request_execution_scope(request)
    # ``default`` is the legacy local-mode default.  In server mode the
    # authenticated header is authoritative; an explicit non-default query
    # must match it exactly.
    if requested_workspace.strip() not in {"", "default", scope.workspace_id}:
        raise APIError(
            status_code=403,
            code="workspace_scope_denied",
            message="Workspace scope is not authorized.",
        )
    return scope


def _assert_workspace(record: dict[str, object], workspace_id: str) -> None:
    """Fail closed if a tenant-scoped PostgreSQL row crosses workspace scope."""

    if str(record.get("workspace_id", "")) != workspace_id:
        raise APIError(
            status_code=403,
            code="workspace_scope_denied",
            message="Workspace scope is not authorized.",
        )


def _assert_records_workspace(records: list[dict[str, object]], workspace_id: str) -> None:
    for record in records:
        _assert_workspace(record, workspace_id)


def _server_source() -> dict[str, object]:
    return {"kind": "postgresql-consolidation-close", "server_mode": True}


@router.get("/periods")
def list_periods(
    request: Request,
    current_user: ConsolidationRead,
    workspace: str = Query(default="default", min_length=1, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List scope-bound close periods with immutable lifecycle metadata."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, workspace)
        records = execute_postgres_consolidation_close(
            request,
            lambda repository, _tenant: repository.list_periods(
                workspace=scope.workspace_id,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
        )
        _assert_records_workspace(records, scope.workspace_id)
        return {"periods": records, "source": _server_source()}

    try:
        records = _repository(connection).list_periods(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_periods_failed", exc) from exc
    return {"periods": records, "source": {"kind": "sqlite-consolidation-close", "workspace": workspace}}


@router.get("/periods/{period_id}")
def get_period(
    period_id: str,
    request: Request,
    current_user: ConsolidationRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return one replay-checked close period."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, "")
        period = execute_postgres_consolidation_close(
            request,
            lambda repository, _tenant: repository.get_period(period_id, actor_label=current_user.id),
        )
        _assert_workspace(period, scope.workspace_id)
        return {"period": period, "source": _server_source()}

    try:
        period = _repository(connection).get_period(period_id, actor_label=current_user.username)
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_period_failed", exc) from exc
    return {"period": period, "source": {"kind": "sqlite-consolidation-close"}}


@router.get("/runs")
def list_runs(
    request: Request,
    current_user: ConsolidationRead,
    workspace: str = Query(default="default", min_length=1, max_length=120),
    status: str = Query(default="", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List close runs while replay-verifying every persisted worksheet."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, workspace)
        records = execute_postgres_consolidation_close(
            request,
            lambda repository, _tenant: repository.list_runs(
                workspace=scope.workspace_id,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=current_user.id,
            ),
        )
        _assert_records_workspace(records, scope.workspace_id)
        return {"runs": records, "source": _server_source()}

    try:
        records = _repository(connection).list_runs(
            workspace=workspace, status=status, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_runs_failed", exc) from exc
    return {"runs": records, "source": {"kind": "sqlite-consolidation-close", "workspace": workspace}}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    request: Request,
    current_user: ConsolidationRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return one run, journal lines, effects, and replay-verified worksheet."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, "")
        run = execute_postgres_consolidation_close(
            request,
            lambda repository, _tenant: repository.get_run(run_id, actor_label=current_user.id),
        )
        _assert_workspace(run, scope.workspace_id)
        return {"run": run, "source": _server_source()}

    try:
        run = _repository(connection).get_run(run_id, actor_label=current_user.username)
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_run_failed", exc) from exc
    return {"run": run, "source": {"kind": "sqlite-consolidation-close"}}


@router.post("/runs/{run_id}/certification")
def prepare_certification(
    run_id: str,
    request: Request,
    payload: CertificationRequest,
    current_user: ConsolidationCertify,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Prepare maker-checker certification metadata for a posted close run."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, "")

        def prepare(repository: PostgresConsolidationCloseRepository, _tenant: str) -> dict[str, object]:
            run = repository.get_run(run_id, actor_label=current_user.id)
            _assert_workspace(run, scope.workspace_id)
            return repository.prepare_certification(
                run_id,
                note=payload.note,
                actor_label=current_user.id,
            )

        certification = execute_postgres_consolidation_close(request, prepare)
        return {"certification": certification, "source": _server_source()}

    try:
        certification = _repository(connection).prepare_certification(
            run_id,
            note=payload.note,
            actor_label=current_user.username,
        )
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_certification_prepare_failed", exc) from exc
    return {"certification": certification, "source": {"kind": "sqlite-consolidation-close"}}


@router.post("/runs/{run_id}/certification/review")
def review_certification(
    run_id: str,
    request: Request,
    payload: CertificationRequest,
    current_user: ConsolidationReview,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Review certification metadata with an actor independent of preparation."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, "")

        def review(repository: PostgresConsolidationCloseRepository, _tenant: str) -> dict[str, object]:
            run = repository.get_run(run_id, actor_label=current_user.id)
            _assert_workspace(run, scope.workspace_id)
            return repository.review_certification(
                run_id,
                note=payload.note,
                actor_label=current_user.id,
            )

        certification = execute_postgres_consolidation_close(request, review)
        return {"certification": certification, "source": _server_source()}

    try:
        certification = _repository(connection).review_certification(
            run_id,
            note=payload.note,
            actor_label=current_user.username,
        )
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_certification_review_failed", exc) from exc
    return {"certification": certification, "source": {"kind": "sqlite-consolidation-close"}}


@router.get("/runs/{run_id}/certification")
def get_certification(
    run_id: str,
    request: Request,
    current_user: ConsolidationRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return replay-scoped certification metadata for one close run."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, "")

        def fetch(repository: PostgresConsolidationCloseRepository, _tenant: str) -> dict[str, object]:
            run = repository.get_run(run_id, actor_label=current_user.id)
            _assert_workspace(run, scope.workspace_id)
            return repository.get_certification(run_id, actor_label=current_user.id)

        certification = execute_postgres_consolidation_close(request, fetch)
        return {"certification": certification, "source": _server_source()}

    try:
        certification = _repository(connection).get_certification(run_id, actor_label=current_user.username)
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_certification_failed", exc) from exc
    return {"certification": certification, "source": {"kind": "sqlite-consolidation-close"}}


@router.get("/summary")
def summary(
    request: Request,
    current_user: ConsolidationRead,
    workspace: str = Query(default="default", min_length=1, max_length=120),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return bounded lifecycle counts for one workspace."""

    if server_consolidation_close_enabled(request):
        scope = _server_scope(request, workspace)
        value = execute_postgres_consolidation_close(
            request,
            lambda repository, _tenant: repository.summary(
                workspace=scope.workspace_id,
                actor_label=current_user.id,
            ),
        )
        return {"summary": value.to_dict(), "source": _server_source()}

    try:
        value = _repository(connection).summary(workspace=workspace, actor_label=current_user.username)
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise _error("consolidation_summary_failed", exc) from exc
    return {"summary": value.to_dict(), "source": {"kind": "sqlite-consolidation-close", "workspace": workspace}}
