"""Authentication routes for local API sessions."""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict, deque
from threading import Lock
from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import bearer_scheme, get_current_user, get_db
from reconforge.api.errors import APIError
from reconforge.api.security import SessionError, create_session, revoke_token
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

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
_login_failures: dict[str, deque[float]] = defaultdict(deque)
_login_failures_lock = Lock()


def _failure_state(request: Request) -> tuple[dict[str, deque[float]], Lock]:
    store = getattr(request.app.state, "login_failures", None)
    lock = getattr(request.app.state, "login_failures_lock", None)
    if not isinstance(store, dict) or lock is None:
        return _login_failures, _login_failures_lock
    return store, lock


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
    now = _now()
    attempts_state, lock = _failure_state(request)
    with lock:
        attempts = _cleanup_and_get_attempts(attempts_state[key], now)
        return len(attempts) >= _MAX_LOGIN_ATTEMPTS


def _record_failed_attempt(request: Request, key: str) -> None:
    now = _now()
    attempts_state, lock = _failure_state(request)
    with lock:
        attempts = _cleanup_and_get_attempts(attempts_state[key], now)
        attempts.append(now)


def _clear_login_failures(request: Request, key: str) -> None:
    attempts_state, lock = _failure_state(request)
    with lock:
        attempts_state.pop(key, None)


def _raise_rate_limited() -> None:
    raise APIError(status_code=429, code="login_rate_limited", message="Too many failed login attempts. Try again later.")


def _raise_invalid_credentials() -> None:
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
    connection: sqlite3.Connection = Depends(get_db),
) -> LoginResponse:
    """Create a local API session for valid local credentials."""

    key = _login_failure_key(request, payload.username)
    if _is_rate_limited_for_request(request, key):
        _raise_rate_limited()

    try:
        user = LocalAuthService(connection).authenticate_user(username=payload.username, password=payload.password)
        if user is None:
            _record_failed_attempt(request, key)
            _raise_invalid_credentials()
        _clear_login_failures(request, key)
        session = create_session(connection, user=cast(LocalUser, user))
    except APIError:
        raise
    except (DatabaseError, AuthRepositoryError, AuthServiceError, SessionError) as exc:
        _record_failed_attempt(request, key)
        raise APIError(status_code=401, code="invalid_credentials", message="Invalid username or password.") from exc

    return LoginResponse(access_token=session.token, expires_at=session.expires_at)


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Revoke the current local API session."""

    token = credentials.credentials if credentials is not None else ""
    try:
        revoked = revoke_token(connection, token=token)
    except (DatabaseError, SessionError) as exc:
        raise APIError(status_code=400, code="logout_failed", message="Unable to revoke local API session.") from exc
    return {"revoked": revoked, "username": current_user.username}


@router.get("/me")
def me(
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Return the active local API user without credential material."""

    try:
        roles = LocalAuthService(connection).roles.user_roles(current_user.username)
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="user_read_failed", message="Unable to read local user.") from exc
    payload = _user_payload(current_user)
    payload["roles"] = roles
    return payload
