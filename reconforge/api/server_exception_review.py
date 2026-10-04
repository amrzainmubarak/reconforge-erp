"""Request-scoped PostgreSQL operations for governed exception review."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.exception_review import ExceptionReviewApplicationService
from reconforge.domain.exception_review import (
    ExceptionReviewAssigneeError,
    ExceptionReviewConflictError,
    ExceptionReviewCreatorIdentityError,
    ExceptionReviewError,
    ExceptionReviewNotFoundError,
    ExceptionReviewReviewerError,
    ExceptionReviewScope,
    ExceptionReviewSeparationError,
)
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_exceptions import (
    PostgresExceptionQueueError,
    PostgresExceptionQueueRepository,
)

T = TypeVar("T")
ExceptionReviewOperation = Callable[[ExceptionReviewApplicationService, ExceptionReviewScope], T]


def get_postgres_exception_review_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicitly configured PostgreSQL exception-review factory."""

    value = getattr(request.app.state, "postgres_exception_review_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_exception_review_enabled(request: Request) -> bool:
    """Return whether exception routes must use the PostgreSQL review boundary."""

    return get_postgres_exception_review_factory(request) is not None


def execute_postgres_exception_review(request: Request, operation: ExceptionReviewOperation[T]) -> T:
    """Execute a typed exception-review operation under request hierarchy RLS."""

    factory = get_postgres_exception_review_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="exception_review_unavailable",
            message="Server exception review is unavailable.",
        )
    request_scope = request_execution_scope(request)
    review_scope = ExceptionReviewScope(
        tenant_id=request_scope.tenant_id,
        workspace_id=request_scope.workspace_id,
        organization_id=request_scope.organization_id,
        legal_entity_id=request_scope.legal_entity_id,
    )
    try:
        with PostgresTenantBoundary(factory).transaction(
            request_scope.tenant_id,
            organization_id=request_scope.organization_id,
            workspace_id=request_scope.workspace_id,
            legal_entity_id=request_scope.legal_entity_id,
        ) as connection:
            service = ExceptionReviewApplicationService(
                PostgresExceptionQueueRepository(connection, request_scope.tenant_id)
            )
            return operation(service, review_scope)
    except APIError:
        raise
    except ExceptionReviewNotFoundError as exc:
        raise APIError(
            status_code=404,
            code="exception_not_found",
            message="Exception review record was not found in the authorized scope.",
        ) from exc
    except ExceptionReviewCreatorIdentityError as exc:
        raise APIError(
            status_code=409,
            code="exception_creator_identity_required",
            message=str(exc),
        ) from exc
    except ExceptionReviewReviewerError as exc:
        raise APIError(
            status_code=409,
            code="exception_reviewer_ineligible",
            message=str(exc),
        ) from exc
    except ExceptionReviewSeparationError as exc:
        raise APIError(status_code=409, code="exception_self_review_refused", message=str(exc)) from exc
    except ExceptionReviewAssigneeError as exc:
        raise APIError(
            status_code=409,
            code="exception_reviewer_assignment_required",
            message=str(exc),
        ) from exc
    except ExceptionReviewConflictError as exc:
        raise APIError(status_code=409, code="exception_review_conflict", message=str(exc)) from exc
    except ExceptionReviewError as exc:
        raise APIError(status_code=400, code="exception_review_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError, PostgresExceptionQueueError) as exc:
        raise APIError(
            status_code=503,
            code="exception_review_unavailable",
            message="Server exception review is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="exception_review_unavailable",
            message="Server exception review is temporarily unavailable.",
        ) from exc


__all__ = [
    "ExceptionReviewOperation",
    "execute_postgres_exception_review",
    "get_postgres_exception_review_factory",
    "server_exception_review_enabled",
]
