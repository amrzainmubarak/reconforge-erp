"""Authentication routes for local API sessions."""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.api.browser_session import BROWSER_SESSION_COOKIE, issue_browser_csrf_token
from reconforge.api.dependencies import (
    bearer_scheme,
    get_auth_db,
    get_current_user,
    session_token_from_request,
)
from reconforge.api.errors import APIError
from reconforge.api.security import SessionError, create_session, revoke_token
from reconforge.api.server_identity import (
    execute_postgres_federation,
    execute_postgres_identity,
    execute_postgres_service_account,
    server_identity_enabled,
)
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.federation import FederationError, FederationRequest, FederationService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id
from reconforge.infrastructure.postgres_federation import PostgresFederationError
from reconforge.infrastructure.postgres_privileged_sessions import (
    PostgresPrivilegedSessionRepository,
    PrivilegedSessionError,
)
from reconforge.infrastructure.redis import (
    RedisConfigurationError,
    RedisDataError,
    RedisOperationError,
    RedisUnavailableError,
    TenantRedisStore,
)
from reconforge.platform.common import ServerPrincipal, current_server_principal

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


class BrowserLoginResponse(BaseModel):
    """A browser session result that never serializes its bearer credential."""

    csrf_token: str
    expires_at: str


class StepUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)


class StepUpResponse(BaseModel):
    method: str = "password_reauthentication"
    expires_at: str


class FederationChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class FederationChallengeResponse(BaseModel):
    challenge_id: str
    protocol: str
    expires_at: str
    nonce: str | None = None
    request_id: str | None = None


class FederatedLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    encoded_assertion: str = Field(min_length=1, max_length=2_000_000)
    challenge_id: str = Field(min_length=32, max_length=256)
    expected_nonce: str | None = Field(default=None, min_length=16, max_length=256)
    request_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_one_correlation(self) -> FederatedLoginRequest:
        if (self.expected_nonce is None) == (self.request_id is None):
            raise ValueError("Federated login requires exactly one challenge correlation value.")
        return self


class _CapturedFederationAudit:
    def __init__(self) -> None:
        self.outcome = "denied"
        self.reason_code: str | None = "verification_failed"

    def record(self, *, action: str, provider_id: str, outcome: str, reason_code: str | None) -> None:
        del action, provider_id
        self.outcome = outcome
        self.reason_code = reason_code


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
    raise APIError(
        status_code=429, code="login_rate_limited", message="Too many failed login attempts. Try again later."
    )


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

    session = _authenticate_and_create_session(payload, request, connection)
    return LoginResponse(access_token=session.token, expires_at=session.expires_at)


@router.post("/browser/login")
def browser_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> BrowserLoginResponse:
    """Create one HTTPS same-origin browser session without serializing its token."""

    session = _authenticate_and_create_session(payload, request, connection)
    response.set_cookie(
        BROWSER_SESSION_COOKIE,
        session.token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
        max_age=24 * 60 * 60,
    )
    return BrowserLoginResponse(csrf_token=issue_browser_csrf_token(session.token), expires_at=session.expires_at)


def _authenticate_and_create_session(
    payload: LoginRequest,
    request: Request,
    connection: sqlite3.Connection | None,
) -> Any:
    """Authenticate once for either API bearer or same-origin browser session issuance."""

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
                raise APIError(
                    status_code=500, code="db_not_configured", message="API database path is not configured."
                )
            local_user = LocalAuthService(connection).authenticate_user(
                username=payload.username, password=payload.password
            )
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

    return session


@router.post("/federation/challenge")
def federation_challenge(payload: FederationChallengeRequest, request: Request) -> FederationChallengeResponse:
    """Issue one short-lived server challenge for an enabled configured provider."""

    providers = getattr(request.app.state, "federation_providers", {})
    provider = providers.get(payload.provider_id) if isinstance(providers, dict) else None
    if provider is None or not provider.enabled or not server_identity_enabled(request):
        raise APIError(
            status_code=503,
            code="federation_not_configured",
            message="Federated authentication is not configured.",
        )
    challenge = execute_postgres_federation(
        request,
        lambda replay, repository, audit, tenant_id: repository.issue_challenge(
            tenant_id=tenant_id,
            provider_id=provider.id,
            protocol=provider.protocol,
        ),
    )
    return FederationChallengeResponse(
        challenge_id=challenge.challenge_id,
        protocol=challenge.protocol,
        expires_at=challenge.expires_at,
        nonce=challenge.correlation if challenge.protocol == "oidc" else None,
        request_id=challenge.correlation if challenge.protocol == "saml" else None,
    )


@router.post("/federated-login")
def federated_login(payload: FederatedLoginRequest, request: Request) -> LoginResponse:
    """Verify a configured assertion and bind it to pre-provisioned local authority."""

    providers = getattr(request.app.state, "federation_providers", {})
    verifiers = getattr(request.app.state, "federation_verifiers", {})
    if not providers or not verifiers or not server_identity_enabled(request):
        raise APIError(
            status_code=503,
            code="federation_not_configured",
            message="Federated authentication is not configured.",
        )

    def authenticate(replay: Any, repository: Any, audit: Any, tenant_id: str) -> Any | None:
        captured = _CapturedFederationAudit()
        provider = providers.get(payload.provider_id)
        if provider is None:
            return None
        correlation = payload.expected_nonce if provider.protocol == "oidc" else payload.request_id
        if correlation is None or not repository.consume_challenge(
            tenant_id=tenant_id,
            provider_id=provider.id,
            protocol=provider.protocol,
            challenge_id=payload.challenge_id,
            correlation=correlation,
        ):
            audit.record(
                action="federation_authenticate",
                provider_id=payload.provider_id,
                outcome="denied",
                reason_code="challenge_invalid",
            )
            return None
        federation_request = FederationRequest(
            provider_id=payload.provider_id,
            encoded_assertion=payload.encoded_assertion,
            expected_nonce=payload.expected_nonce,
            request_id=payload.request_id,
        )
        service = FederationService(
            providers=providers,
            verifiers=verifiers,
            replay_store=replay,
            audit_sink=captured,
            air_gap_mode=bool(getattr(request.app.state, "federation_air_gap_mode", False)),
        )
        try:
            principal = service.authenticate(federation_request)
            session = repository.complete_login(tenant_id=tenant_id, principal=principal)
        except FederationError:
            audit.record(
                action="federation_authenticate",
                provider_id=payload.provider_id,
                outcome="denied",
                reason_code=captured.reason_code,
            )
            return None
        except PostgresFederationError:
            audit.record(
                action="federation_authenticate",
                provider_id=payload.provider_id,
                outcome="denied",
                reason_code="identity_link_invalid",
            )
            return None
        audit.record(
            action="federation_authenticate",
            provider_id=payload.provider_id,
            outcome="allowed",
            reason_code=None,
        )
        return session

    session = execute_postgres_federation(request, authenticate)
    if session is None:
        raise APIError(
            status_code=401, code="federated_authentication_failed", message="Federated authentication failed."
        )
    return LoginResponse(access_token=session.token, expires_at=session.expires_at)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> dict[str, object]:
    """Revoke the current API session in the configured identity backend."""

    token, transport = session_token_from_request(request, credentials)
    try:
        if server_identity_enabled(request):
            principal = current_server_principal()
            if isinstance(principal, ServerPrincipal) and principal.principal_type == "service_account":
                revoked = execute_postgres_service_account(
                    request,
                    lambda repository, tenant_id: repository.revoke_token(
                        tenant_id=tenant_id, token=token, actor_id=principal.user.id
                    ),
                )
            else:
                revoked = execute_postgres_identity(
                    request,
                    lambda repository, tenant_id: repository.revoke_token(tenant_id=tenant_id, token=token),
                )
        else:
            if connection is None:
                raise APIError(
                    status_code=500, code="db_not_configured", message="API database path is not configured."
                )
            revoked = revoke_token(connection, token=token)
    except APIError:
        raise
    except (DatabaseError, SessionError) as exc:
        raise APIError(status_code=400, code="logout_failed", message="Unable to revoke API session.") from exc
    if transport == "browser_cookie":
        response.delete_cookie(BROWSER_SESSION_COOKIE, path="/")
    return {"revoked": revoked, "username": current_user.username}


@router.post("/step-up")
def step_up(
    payload: StepUpRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: LocalUser = Depends(get_current_user),
) -> StepUpResponse:
    """Reauthenticate the current local-password human session for ten minutes."""

    if not server_identity_enabled(request):
        raise APIError(status_code=404, code="step_up_unavailable", message="Session step-up is unavailable.")
    principal = current_server_principal()
    if not isinstance(principal, ServerPrincipal) or principal.principal_type != "user" or principal.session_id is None:
        raise APIError(status_code=403, code="human_principal_required", message="A human session is required.")
    token, _transport = session_token_from_request(request, credentials)
    try:
        assurance = execute_postgres_identity(
            request,
            lambda repository, tenant_id: PostgresPrivilegedSessionRepository(repository.connection).reauthenticate(
                tenant_id=tenant_id,
                token=token,
                user_id=current_user.id,
                username=current_user.username,
                password=payload.password,
                request_id=str(getattr(request.state, "request_id", "")),
            ),
        )
    except APIError:
        raise
    except PrivilegedSessionError as exc:
        raise APIError(
            status_code=503,
            code="step_up_unavailable",
            message="Session step-up is temporarily unavailable.",
        ) from exc
    if assurance is None or assurance.step_up_expires_at is None:
        raise APIError(status_code=401, code="invalid_credentials", message="Invalid username or password.")
    return StepUpResponse(expires_at=assurance.step_up_expires_at)


@router.get("/me")
def me(
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> dict[str, object]:
    """Return the active API user without credential material."""

    try:
        if server_identity_enabled(request):
            principal = current_server_principal()
            if isinstance(principal, ServerPrincipal) and principal.principal_type == "service_account":
                roles = []
            else:
                roles = execute_postgres_identity(
                    request,
                    lambda repository, tenant_id: repository.user_roles(tenant_id=tenant_id, user_id=current_user.id),
                )
        else:
            if connection is None:
                raise APIError(
                    status_code=500, code="db_not_configured", message="API database path is not configured."
                )
            roles = LocalAuthService(connection).roles.user_roles(current_user.username)
    except APIError:
        raise
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="user_read_failed", message="Unable to read API user.") from exc
    payload = _user_payload(current_user)
    payload["roles"] = roles
    principal = current_server_principal()
    payload["principal_type"] = principal.principal_type if isinstance(principal, ServerPrincipal) else "user"
    if isinstance(principal, ServerPrincipal) and principal.principal_type == "user":
        payload["step_up_active"] = principal.step_up_active
        payload["step_up_expires_at"] = principal.step_up_expires_at
        payload["step_up_method"] = principal.step_up_method
    if isinstance(principal, ServerPrincipal) and principal.principal_type == "service_account":
        payload["permissions"] = sorted(principal.permissions)
    if isinstance(principal, ServerPrincipal):
        payload["authorized_scopes"] = {
            "workspaces": sorted(principal.authorized_workspace_ids),
            "organizations": sorted(principal.authorized_organization_ids),
            "legal_entities": sorted(principal.authorized_legal_entity_ids),
        }
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
