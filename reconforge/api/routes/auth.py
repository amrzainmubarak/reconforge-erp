"""Authentication routes for local API sessions."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
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
def login(payload: LoginRequest, connection: sqlite3.Connection = Depends(get_db)) -> LoginResponse:
    """Create a local API session for valid local credentials."""

    try:
        user = LocalAuthService(connection).authenticate_user(username=payload.username, password=payload.password)
        if user is None:
            raise APIError(status_code=401, code="invalid_credentials", message="Invalid username or password.")
        session = create_session(connection, user=user)
    except APIError:
        raise
    except (DatabaseError, AuthRepositoryError, AuthServiceError, SessionError) as exc:
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
