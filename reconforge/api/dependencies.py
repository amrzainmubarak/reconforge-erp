"""FastAPI dependencies for the local REST API foundation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from reconforge.api.errors import APIError
from reconforge.api.security import SessionError, authenticate_token
from reconforge.api.server_identity import authenticate_server_request, server_identity_enabled
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError, connect
from reconforge.db.tenancy import (
    InvalidTenantIdError,
    TenantDatabaseNotFoundError,
    TenantDatabaseRouter,
    TenantRoutingError,
)
from reconforge.platform.common import ServerPrincipal, current_server_principal, server_principal_context

bearer_scheme = HTTPBearer(auto_error=False)


class CursorPaginationParams(BaseModel):
    """Standardized cursor-based pagination parameters."""

    cursor: str | None = Field(default=None, description="Opaque cursor token for next page.")
    limit: int = Field(default=50, ge=1, le=500, description="Page size limit (1-500).")


def get_cursor_pagination(
    cursor: str | None = Query(default=None, description="Opaque cursor token for next page."),
    limit: int = Query(default=50, ge=1, le=500, description="Page size limit (1-500)."),
) -> CursorPaginationParams:
    """FastAPI dependency providing validated cursor pagination parameters."""

    resolved_cursor = None if not isinstance(cursor, str) else cursor
    resolved_limit = 50 if not isinstance(limit, int) else limit
    return CursorPaginationParams(cursor=resolved_cursor, limit=resolved_limit)


def get_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> str | None:
    """Extract and validate request Idempotency-Key header.

    Returns normalized non-empty string or None if absent.
    Raises APIError(400) if the provided key is blank.
    """

    key = idempotency_key or x_idempotency_key
    if key is not None:
        cleaned = key.strip()
        if not cleaned:
            raise APIError(status_code=400, code="invalid_idempotency_key", message="Idempotency key must not be blank.")
        return cleaned
    return None


def get_db_path(request: Request) -> Path:
    """Return the request-scoped SQLite path, enforcing tenant mode when configured."""

    tenant_router = getattr(request.app.state, "tenant_db_router", None)
    if isinstance(tenant_router, TenantDatabaseRouter):
        tenant_id = request.headers.get("x-reconforge-tenant", "")
        if not tenant_id:
            raise APIError(
                status_code=400,
                code="tenant_required",
                message="X-ReconForge-Tenant is required for tenant-isolated API mode.",
            )
        try:
            return tenant_router.path_for(tenant_id, require_exists=True)
        except InvalidTenantIdError as exc:
            raise APIError(status_code=400, code="invalid_tenant", message=str(exc)) from exc
        except TenantDatabaseNotFoundError as exc:
            raise APIError(status_code=503, code="tenant_unavailable", message="Tenant database is unavailable.") from exc
        except TenantRoutingError as exc:
            raise APIError(status_code=503, code="tenant_unavailable", message="Tenant database is unavailable.") from exc
    value = getattr(request.app.state, "db_path", None)
    if value is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    return Path(value)


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """Open and close one SQLite connection per request."""

    try:
        connection = connect(get_db_path(request), require_exists=True)
    except DatabaseError as exc:
        raise APIError(status_code=503, code="database_unavailable", message=str(exc)) from exc
    try:
        yield connection
    finally:
        connection.close()


def get_local_db(request: Request) -> Iterator[sqlite3.Connection | None]:
    """Open SQLite only for local routes that are not served by PostgreSQL."""

    if server_identity_enabled(request):
        yield None
        return
    yield from get_db(request)


def get_auth_db(request: Request) -> Iterator[sqlite3.Connection | None]:
    """Open the local auth database only when PostgreSQL identity is disabled."""

    if server_identity_enabled(request):
        yield None
        return
    yield from get_db(request)


def _token_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    return credentials.credentials


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> Iterator[LocalUser]:
    """Authenticate the bearer token against the configured identity backend."""

    token = _token_from_credentials(credentials)
    if server_identity_enabled(request):
        request_principal = getattr(request.state, "server_principal", None)
        if isinstance(request_principal, ServerPrincipal):
            yield request_principal.user
            return
        try:
            authenticated = authenticate_server_request(request, token)
        except APIError:
            raise
        if authenticated is None:
            raise APIError(status_code=401, code="invalid_token", message="Invalid or expired token.")
        user, permissions = authenticated
        principal = ServerPrincipal(user=user, permissions=permissions)
        request.state.server_principal = principal
        with server_principal_context(principal):
            yield user
        return
    if connection is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    try:
        local_user = authenticate_token(connection, token=token)
    except (DatabaseError, SessionError, AuthRepositoryError) as exc:
        raise APIError(status_code=401, code="invalid_token", message="Invalid or expired token.") from exc
    if local_user is None:
        raise APIError(status_code=401, code="invalid_token", message="Invalid or expired token.")
    yield local_user


def require_permission(permission: str) -> Callable[..., LocalUser]:
    """Build a dependency requiring one local RBAC permission."""

    def dependency(
        request: Request,
        current_user: LocalUser = Depends(get_current_user),
        connection: sqlite3.Connection | None = Depends(get_auth_db),
    ) -> LocalUser:
        if server_identity_enabled(request):
            principal = getattr(request.state, "server_principal", None)
            if not isinstance(principal, ServerPrincipal):
                principal = current_server_principal()
            allowed = principal is not None and principal.user.id == current_user.id and permission in principal.permissions
            if not allowed:
                raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
            return current_user
        if connection is None:
            raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
        try:
            allowed = LocalAuthService(connection).user_has_permission(username=current_user.username, permission=permission)
        except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.") from exc
        if not allowed:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
        return current_user

    return dependency


def require_any_permission(permissions: set[str]) -> Callable[..., LocalUser]:
    """Build a dependency requiring at least one local RBAC permission."""

    def dependency(
        request: Request,
        current_user: LocalUser = Depends(get_current_user),
        connection: sqlite3.Connection | None = Depends(get_auth_db),
    ) -> LocalUser:
        if server_identity_enabled(request):
            principal = getattr(request.state, "server_principal", None)
            if not isinstance(principal, ServerPrincipal):
                principal = current_server_principal()
            allowed = principal is not None and principal.user.id == current_user.id and bool(
                principal.permissions.intersection(permissions)
            )
            if not allowed:
                raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
            return current_user
        if connection is None:
            raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
        try:
            service = LocalAuthService(connection)
            allowed = any(
                service.user_has_permission(username=current_user.username, permission=permission)
                for permission in permissions
            )
        except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.") from exc
        if not allowed:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
        return current_user

    return dependency
