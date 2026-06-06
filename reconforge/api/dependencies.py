"""FastAPI dependencies for the local REST API foundation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from reconforge.api.errors import APIError
from reconforge.api.security import SessionError, authenticate_token
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError, connect

bearer_scheme = HTTPBearer(auto_error=False)


def get_db_path(request: Request) -> Path:
    """Return the app-local SQLite path."""

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


def _token_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    return credentials.credentials


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    connection: sqlite3.Connection = Depends(get_db),
) -> LocalUser:
    """Authenticate the bearer token and return the active local user."""

    token = _token_from_credentials(credentials)
    try:
        user = authenticate_token(connection, token=token)
    except (DatabaseError, SessionError, AuthRepositoryError) as exc:
        raise APIError(status_code=401, code="invalid_token", message="Invalid or expired token.") from exc
    if user is None:
        raise APIError(status_code=401, code="invalid_token", message="Invalid or expired token.")
    return user


def require_permission(permission: str) -> Callable[[LocalUser, sqlite3.Connection], LocalUser]:
    """Build a dependency requiring one local RBAC permission."""

    def dependency(
        current_user: LocalUser = Depends(get_current_user),
        connection: sqlite3.Connection = Depends(get_db),
    ) -> LocalUser:
        try:
            allowed = LocalAuthService(connection).user_has_permission(username=current_user.username, permission=permission)
        except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.") from exc
        if not allowed:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
        return current_user

    return dependency


def require_any_permission(permissions: set[str]) -> Callable[[LocalUser, sqlite3.Connection], LocalUser]:
    """Build a dependency requiring at least one local RBAC permission."""

    def dependency(
        current_user: LocalUser = Depends(get_current_user),
        connection: sqlite3.Connection = Depends(get_db),
    ) -> LocalUser:
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
