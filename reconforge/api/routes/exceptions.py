"""Unified exception queue routes for the local API."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permissions,
    get_local_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_exception_review import (
    execute_postgres_exception_review,
    server_exception_review_enabled,
)
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.auth.field_access import (
    project_exception,
    project_exception_review,
    project_exception_review_list_page,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.domain.exception_review import (
    ExceptionReviewAssignment,
    ExceptionReviewError,
    ExceptionReviewHistoryPage,
    ExceptionReviewListPage,
    ExceptionReviewQuery,
    ExceptionReviewTransition,
)
from reconforge.platform.common import PlatformError
from reconforge.platform.exceptions import ExceptionQueueService

router = APIRouter(prefix="/exceptions", tags=["exceptions"])

ExceptionsRead = Annotated[LocalUser, Depends(require_any_permission({"exceptions.read", "exceptions.manage"}))]
ExceptionsManage = Annotated[LocalUser, Depends(require_permission("exceptions.manage"))]


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=1)


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    reason: str = Field(default="", max_length=1_000)
    expected_version: int | None = Field(default=None, ge=1)


def _project_exception(value: Mapping[str, object]) -> dict[str, object]:
    return project_exception(value).visible


def _project_exceptions(values: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_project_exception(value) for value in values]


def _project_server_exception(value: Mapping[str, object]) -> dict[str, object]:
    return project_exception_review(value).visible


def _project_server_exceptions(values: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_project_server_exception(value) for value in values]


def _local_connection(request: Request, connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if server_exception_review_enabled(request):
        raise APIError(
            status_code=501,
            code="exceptions_server_backend_unavailable",
            message="The unified exception queue is not exposed by the PostgreSQL server boundary.",
        )
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local exception queue database is not configured.")
    return connection


def _server_scope(request: Request, permissions: frozenset[str]) -> RequestExecutionScope:
    scope = request_execution_scope(request)
    enforce_server_scoped_permissions(
        request,
        permissions=permissions,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id,
        entity_id=scope.legal_entity_id,
        object_type="exception_case",
    )
    return scope


def _required_expected_version(value: int | None) -> int:
    if value is None:
        raise APIError(
            status_code=400,
            code="exception_review_expected_version_required",
            message="Expected version is required for server exception review.",
        )
    return value


@router.get("")
def list_exceptions(
    request: Request,
    current_user: ExceptionsRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    period: str = "",
    entity: str = "",
    account: str = "",
    control: str = "",
    risk: str = "",
    owner: str = "",
    status: str = "",
    limit: int = 100,
    cursor: str = "",
) -> dict[str, object]:
    """List unified DB-backed exceptions."""

    if server_exception_review_enabled(request):
        _server_scope(request, frozenset({"exceptions.read", "exceptions.manage"}))
        try:
            query = ExceptionReviewQuery(
                period_name=period,
                entity_code=entity,
                account_code=account,
                control_code=control,
                risk_rating=risk,
                owner=owner,
                status=status,
            )
            page = ExceptionReviewListPage(limit=limit, cursor=cursor)
        except ExceptionReviewError as exc:
            raise APIError(status_code=400, code="exception_review_invalid", message=str(exc)) from exc
        result = execute_postgres_exception_review(
            request,
            lambda service, review_scope: service.list_page(review_scope, query, page),
        )
        records = result.get("records") if isinstance(result, Mapping) else None
        pagination = result.get("pagination") if isinstance(result, Mapping) else None
        if not isinstance(records, list) or not isinstance(pagination, Mapping):
            raise APIError(
                status_code=503,
                code="exception_review_unavailable",
                message="Server exception review is temporarily unavailable.",
            )
        return {
            "exceptions": _project_server_exceptions(records),
            "pagination": project_exception_review_list_page(pagination).visible,
        }
    try:
        records = ExceptionQueueService(_local_connection(request, connection)).list(
            period_name=period,
            entity_code=entity,
            account_code=account,
            control_code=control,
            risk_rating=risk,
            owner=owner,
            status=status,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exceptions_list_failed", message=str(exc)) from exc
    return {"exceptions": _project_exceptions(records)}


@router.get("/{exception_id}")
def get_exception(
    exception_id: str,
    request: Request,
    current_user: ExceptionsRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    history_limit: int = 100,
    history_cursor: str = "",
) -> dict[str, object]:
    """Read one exception and its retained review evidence when server-backed."""

    if server_exception_review_enabled(request):
        _server_scope(request, frozenset({"exceptions.read", "exceptions.manage"}))
        try:
            history_page = ExceptionReviewHistoryPage(limit=history_limit, cursor=history_cursor)
        except ExceptionReviewError as exc:
            raise APIError(status_code=400, code="exception_review_invalid", message=str(exc)) from exc
        record = execute_postgres_exception_review(
            request,
            lambda service, review_scope: service.get(review_scope, exception_id, history_page),
        )
        return {"exception": _project_server_exception(record)}
    try:
        record = ExceptionQueueService(_local_connection(request, connection)).get(exception_id)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=404, code="exception_not_found", message=str(exc)) from exc
    return {"exception": _project_exception(record)}


@router.post("/{exception_id}/assign")
def assign_exception(
    exception_id: str,
    request: Request,
    payload: AssignRequest,
    current_user: ExceptionsManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Assign a unified exception."""

    if server_exception_review_enabled(request):
        _server_scope(request, frozenset({"exceptions.manage"}))
        try:
            command = ExceptionReviewAssignment(
                exception_id=exception_id,
                owner=payload.owner,
                expected_version=_required_expected_version(payload.expected_version),
                actor_id=current_user.id,
                actor_label=current_user.username,
            )
        except ExceptionReviewError as exc:
            raise APIError(status_code=400, code="exception_review_invalid", message=str(exc)) from exc
        record = execute_postgres_exception_review(
            request,
            lambda service, review_scope: service.assign(review_scope, command),
        )
        return {"exception": _project_server_exception(record)}
    try:
        record = ExceptionQueueService(_local_connection(request, connection)).assign(
            exception_id, owner=payload.owner, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exception_assign_failed", message=str(exc)) from exc
    return {"exception": _project_exception(record)}


@router.post("/{exception_id}/status")
def set_exception_status(
    exception_id: str,
    request: Request,
    payload: StatusRequest,
    current_user: ExceptionsManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Set a unified exception status."""

    if server_exception_review_enabled(request):
        _server_scope(request, frozenset({"exceptions.manage"}))
        try:
            command = ExceptionReviewTransition(
                exception_id=exception_id,
                status=payload.status,
                expected_version=_required_expected_version(payload.expected_version),
                actor_id=current_user.id,
                actor_label=current_user.username,
                reason=payload.reason,
            )
        except ExceptionReviewError as exc:
            raise APIError(status_code=400, code="exception_review_invalid", message=str(exc)) from exc
        record = execute_postgres_exception_review(
            request,
            lambda service, review_scope: service.transition(review_scope, command),
        )
        return {"exception": _project_server_exception(record)}
    try:
        record = ExceptionQueueService(_local_connection(request, connection)).set_status(
            exception_id, status=payload.status, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exception_status_failed", message=str(exc)) from exc
    return {"exception": _project_exception(record)}
