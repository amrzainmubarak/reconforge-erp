"""Authentication routes for local API sessions."""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import bearer_scheme, get_auth_db, get_current_user
from reconforge.api.errors import APIError
from reconforge.api.security import SessionError, create_session, revoke_token
from reconforge.api.server_identity import execute_postgres_identity, server_identity_enabled
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id
from reconforge.infrastructure.redis import (
    RedisConfigurationError,
    RedisDataError,
    RedisOperationError,
    RedisUnavailableError,
    TenantRedisStore,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


_LOGIN_ATTEMPT_WINDOW_SECONDS = 60 * 5
_MAX_LOGIN_ATTEMPTS = 8
_REDIS_RATE_LIMIT_BUCKET = "login"
_login_failures: dict[str, deque[float]] = defaultdict(deque)
_login_failures_lock = Lock()


def _failure_state(request: Request) -> tuple[dict[str, deque[float]], Lock]:
    store = getattr(request.app.state, "login_failures", None)
    lock = getattr(request.app.state, "login_failures_lock", None)
    if not isinstance(store, dict) or lock is None:
        return _login_failures, _login_failures_lock
    return store, lock


def _redis_store(request: Request) -> TenantRedisStore | None:
    value = getattr(request.app.state, "redis_store", None)
    return value if isinstance(value, TenantRedisStore) else None


def _rate_limit_tenant(request: Request) -> str:
    raw_tenant = request.headers.get("x-reconforge-tenant") or "local"
    try:
        return normalize_scope_id(raw_tenant)
    except PostgresConfigurationError:
        # Invalid tenant headers are rejected by the database dependency. Use
        # a safe fixed bucket here so the rate limiter never interpolates input.
        return "invalid"


def _raise_redis_unavailable(exc: Exception) -> None:
    raise APIError(
        status_code=503,
        code="coordination_unavailable",
        message="Authentication coordination is temporarily unavailable.",
    ) from exc


def _login_failure_key(request: Request, username: str) -> str:
    normalized_user = (username or "").strip().lower()
    client = request.client
    host = client.host if client is not None else "unknown"
    return f"{host}:{normalized_user}"


def _now() -> float:
    return time.time()


def _cleanup_and_get_attempts(attempts: deque[float], now: float) -> deque[float]:
    while attempts and attempts[0] < now - _LOGIN_ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def _is_rate_limited_for_request(request: Request, key: str) -> bool:
    redis_store = _redis_store(request)
    if redis_store is not None:
        try:
            return (
                redis_store.rate_limit_count(_rate_limit_tenant(request), _REDIS_RATE_LIMIT_BUCKET, key)
                >= _MAX_LOGIN_ATTEMPTS
            )
        except (RedisConfigurationError, RedisDataError, RedisOperationError, RedisUnavailableError) as exc:
            _raise_redis_unavailable(exc)
    now = _now()
    attempts_state, lock = _failure_state(request)
    with lock:
        attempts = _cleanup_and_get_attempts(attempts_state[key], now)
        return len(attempts) >= _MAX_LOGIN_ATTEMPTS


def _record_failed_attempt(request: Request, key: str) -> None:
    redis_store = _redis_store(request)
    if redis_store is not None:
        try:
            redis_store.record_rate_limit_failure(
                _rate_limit_tenant(request),
                _REDIS_RATE_LIMIT_BUCKET,
                key,
                window_seconds=_LOGIN_ATTEMPT_WINDOW_SECONDS,
            )
        except (RedisConfigurationError, RedisDataError, RedisOperationError, RedisUnavailableError) as exc:
            _raise_redis_unavailable(exc)
        return
    now = _now()
    attempts_state, lock = _failure_state(request)
    with lock:
        attempts = _cleanup_and_get_attempts(attempts_state[key], now)
        attempts.append(now)


def _clear_login_failures(request: Request, key: str) -> None:
    redis_store = _redis_store(request)
    if redis_store is not None:
        try:
            redis_store.clear_rate_limit(_rate_limit_tenant(request), _REDIS_RATE_LIMIT_BUCKET, key)
        except (RedisConfigurationError, RedisDataError, RedisOperationError, RedisUnavailableError) as exc:
            _raise_redis_unavailable(exc)
        return
    attempts_state, lock = _failure_state(request)
    with lock:
        attempts_state.pop(key, None)


def _raise_rate_limited() -> NoReturn:
    raise APIError(status_code=429, code="login_rate_limited", message="Too many failed login attempts. Try again later.")


def _raise_invalid_credentials() -> NoReturn:
    raise APIError(status_code=401, code="invalid_credentials", message="Invalid username or password.")


def _user_payload(user: LocalUser) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "disabled": user.disabled,
        "created_at": user.created_at,
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> LoginResponse:
    """Create an API session using the configured local or server identity backend."""

    key = _login_failure_key(request, payload.username)
    if _is_rate_limited_for_request(request, key):
        _raise_rate_limited()

    try:
        if server_identity_enabled(request):
            result = execute_postgres_identity(
                request,
                lambda repository, tenant_id: _server_authenticate_and_create_session(
                    repository,
                    tenant_id,
                    username=payload.username,
                    password=payload.password,
                ),
            )
            if result is None:
                _record_failed_attempt(request, key)
                _raise_invalid_credentials()
            user, session = result
            _clear_login_failures(request, key)
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
            local_user = LocalAuthService(connection).authenticate_user(username=payload.username, password=payload.password)
            if local_user is None:
                _record_failed_attempt(request, key)
                _raise_invalid_credentials()
            _clear_login_failures(request, key)
            user = local_user
            session = create_session(connection, user=user)
    except APIError:
        raise
    except (DatabaseError, AuthRepositoryError, AuthServiceError, SessionError) as exc:
        _record_failed_attempt(request, key)
        raise APIError(status_code=401, code="invalid_credentials", message="Invalid username or password.") from exc

    return LoginResponse(access_token=session.token, expires_at=session.expires_at)


@router.post("/logout")
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> dict[str, object]:
    """Revoke the current API session in the configured identity backend."""

    token = credentials.credentials if credentials is not None else ""
    try:
        if server_identity_enabled(request):
            revoked = execute_postgres_identity(
                request,
                lambda repository, tenant_id: repository.revoke_token(tenant_id=tenant_id, token=token),
            )
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
            revoked = revoke_token(connection, token=token)
    except APIError:
        raise
    except (DatabaseError, SessionError) as exc:
        raise APIError(status_code=400, code="logout_failed", message="Unable to revoke API session.") from exc
    return {"revoked": revoked, "username": current_user.username}


@router.get("/me")
def me(
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> dict[str, object]:
    """Return the active API user without credential material."""

    try:
        if server_identity_enabled(request):
            roles = execute_postgres_identity(
                request,
                lambda repository, tenant_id: repository.user_roles(tenant_id=tenant_id, user_id=current_user.id),
            )
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
            roles = LocalAuthService(connection).roles.user_roles(current_user.username)
    except APIError:
        raise
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="user_read_failed", message="Unable to read API user.") from exc
    payload = _user_payload(current_user)
    payload["roles"] = roles
    return payload


def _server_authenticate_and_create_session(
    repository: Any,
    tenant_id: str,
    *,
    username: str,
    password: str,
) -> tuple[LocalUser, Any] | None:
    """Authenticate and create a server session in one tenant transaction."""

    user = repository.authenticate_user(tenant_id=tenant_id, username=username, password=password)
    if user is None:
        return None
    return user, repository.create_session(tenant_id=tenant_id, user_id=user.id)
