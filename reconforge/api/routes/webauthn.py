"""User-verified WebAuthn enrollment and MFA step-up routes."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconforge.api.dependencies import bearer_scheme, get_current_user
from reconforge.api.errors import APIError
from reconforge.api.server_identity import execute_postgres_webauthn, server_identity_enabled
from reconforge.auth.models import LocalUser
from reconforge.auth.webauthn import (
    WebAuthnError,
    authentication_options,
    credential_id_from_response,
    registration_options,
    verify_authentication,
    verify_registration,
)
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.infrastructure.postgres_privileged_sessions import PostgresPrivilegedSessionRepository
from reconforge.platform.common import ServerPrincipal, current_server_principal

router = APIRouter(prefix="/auth/webauthn", tags=["auth"])
_MAX_CREDENTIAL_RESPONSE_BYTES = 128 * 1024


class CeremonyVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(pattern=r"^wch-[a-f0-9]{32}$")
    credential: dict[str, Any]
    label: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("credential")
    @classmethod
    def bound_credential(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > _MAX_CREDENTIAL_RESPONSE_BYTES:
            raise ValueError("WebAuthn credential response exceeds 128 KiB.")
        return value


def _runtime(request: Request) -> WebAuthnRuntime:
    runtime = getattr(request.app.state, "webauthn_runtime", None)
    if not server_identity_enabled(request) or not isinstance(runtime, WebAuthnRuntime):
        raise APIError(status_code=404, code="webauthn_unavailable", message="WebAuthn is unavailable.")
    return runtime


def _human() -> ServerPrincipal:
    principal = current_server_principal()
    if not isinstance(principal, ServerPrincipal) or principal.principal_type != "user" or principal.session_id is None:
        raise APIError(status_code=403, code="human_principal_required", message="A human session is required.")
    return principal


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def _credential_text(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@router.post("/registration/options")
def begin_registration(request: Request, current_user: LocalUser = Depends(get_current_user)) -> dict[str, Any]:
    runtime = _runtime(request)
    principal = _human()
    if not principal.step_up_active:
        raise APIError(status_code=403, code="step_up_required", message="Recent human reauthentication is required.")
    challenge, credentials = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: (
            repository.issue_challenge(
                tenant_id=tenant_id,
                user_id=current_user.id,
                session_id=principal.session_id or "",
                ceremony="registration",
                request_id=_request_id(request),
            ),
            repository.credentials_for_user(tenant_id=tenant_id, user_id=current_user.id),
        ),
    )
    options = registration_options(
        runtime,
        username=current_user.username,
        display_name=current_user.display_name or current_user.username,
        opaque_user_handle=hashlib.sha256(f"{request.headers.get('x-reconforge-tenant')}:{current_user.id}".encode()).digest(),
        challenge=challenge.challenge,
        credentials=credentials,
    )
    return {"challenge_id": challenge.id, "expires_at": challenge.expires_at, "public_key": options}


@router.post("/registration/verify")
def finish_registration(
    payload: CeremonyVerificationRequest,
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
) -> dict[str, Any]:
    runtime = _runtime(request)
    principal = _human()
    if not principal.step_up_active:
        raise APIError(status_code=403, code="step_up_required", message="Recent human reauthentication is required.")
    challenge = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: repository.consume_challenge(
            tenant_id=tenant_id,
            challenge_id=payload.challenge_id,
            user_id=current_user.id,
            session_id=principal.session_id or "",
            ceremony="registration",
            request_id=_request_id(request),
        ),
    )
    try:
        verified = verify_registration(runtime, response=payload.credential, challenge=challenge.challenge)
    except WebAuthnError as exc:
        raise APIError(status_code=401, code="webauthn_verification_failed", message=str(exc)) from exc
    credential = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: repository.register_credential(
            tenant_id=tenant_id,
            user_id=current_user.id,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            sign_count=verified.sign_count,
            transports=verified.transports,
            device_type=verified.device_type,
            backed_up=verified.backed_up,
            label=payload.label or "WebAuthn authenticator",
            request_id=_request_id(request),
        ),
    )
    return {"credential_id": _credential_text(credential.credential_id), "label": credential.label}


@router.post("/authentication/options")
def begin_authentication(request: Request, current_user: LocalUser = Depends(get_current_user)) -> dict[str, Any]:
    runtime = _runtime(request)
    principal = _human()
    credentials = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: repository.credentials_for_user(
            tenant_id=tenant_id, user_id=current_user.id
        ),
    )
    if not credentials:
        raise APIError(status_code=409, code="webauthn_not_enrolled", message="No WebAuthn credential is enrolled.")
    challenge = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: repository.issue_challenge(
            tenant_id=tenant_id,
            user_id=current_user.id,
            session_id=principal.session_id or "",
            ceremony="authentication",
            request_id=_request_id(request),
        ),
    )
    return {
        "challenge_id": challenge.id,
        "expires_at": challenge.expires_at,
        "public_key": authentication_options(runtime, challenge=challenge.challenge, credentials=credentials),
    }


@router.post("/authentication/verify")
def finish_authentication(
    payload: CeremonyVerificationRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: LocalUser = Depends(get_current_user),
) -> dict[str, Any]:
    runtime = _runtime(request)
    principal = _human()
    challenge = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: repository.consume_challenge(
            tenant_id=tenant_id,
            challenge_id=payload.challenge_id,
            user_id=current_user.id,
            session_id=principal.session_id or "",
            ceremony="authentication",
            request_id=_request_id(request),
        ),
    )
    credential_id = credential_id_from_response(payload.credential)
    credential = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: repository.credential_for_user(
            tenant_id=tenant_id, user_id=current_user.id, credential_id=credential_id
        ),
    )
    if credential is None:
        raise APIError(status_code=401, code="webauthn_verification_failed", message="WebAuthn verification failed.")
    try:
        verified = verify_authentication(
            runtime,
            response=payload.credential,
            challenge=challenge.challenge,
            credential=credential,
        )
    except WebAuthnError as exc:
        raise APIError(status_code=401, code="webauthn_verification_failed", message=str(exc)) from exc
    token = credentials.credentials if credentials is not None else ""
    assurance = execute_postgres_webauthn(
        request,
        lambda repository, tenant_id: _record_verified_authentication(
            repository,
            tenant_id=tenant_id,
            user_id=current_user.id,
            token=token,
            verified=verified,
            request_id=_request_id(request),
        ),
    )
    if assurance is None or assurance.step_up_expires_at is None:
        raise APIError(status_code=401, code="webauthn_verification_failed", message="WebAuthn verification failed.")
    return {"method": "webauthn_user_verified", "expires_at": assurance.step_up_expires_at}


def _record_verified_authentication(
    repository: Any,
    *,
    tenant_id: str,
    user_id: str,
    token: str,
    verified: Any,
    request_id: str,
) -> Any:
    repository.record_authentication(
        tenant_id=tenant_id,
        user_id=user_id,
        credential_id=verified.credential_id,
        previous_sign_count=verified.previous_sign_count,
        new_sign_count=verified.new_sign_count,
        device_type=verified.device_type,
        backed_up=verified.backed_up,
        request_id=request_id,
    )
    return PostgresPrivilegedSessionRepository(repository.connection).record_webauthn_verification(
        tenant_id=tenant_id,
        token=token,
        user_id=user_id,
        credential_id=_credential_text(verified.credential_id),
        request_id=request_id,
    )
