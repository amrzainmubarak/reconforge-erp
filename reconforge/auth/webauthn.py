"""Standards-library adapter for user-verified WebAuthn ceremonies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.infrastructure.postgres_webauthn import WebAuthnCredential
from reconforge.io.structured import StructuredDocumentPolicy, parse_json_document


class WebAuthnError(RuntimeError):
    """Safe ceremony failure without exposing verifier internals."""


_OPTIONS_POLICY = StructuredDocumentPolicy(
    max_file_bytes=128 * 1024,
    max_nodes=4096,
    max_depth=16,
    max_collection_items=1024,
    max_scalar_characters=16 * 1024,
    max_yaml_aliases=1,
)


@dataclass(frozen=True)
class VerifiedRegistration:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    device_type: str
    backed_up: bool
    transports: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedAuthentication:
    credential_id: bytes
    previous_sign_count: int
    new_sign_count: int
    device_type: str
    backed_up: bool


def _library() -> tuple[Any, ...]:
    try:
        from webauthn import (
            base64url_to_bytes,
            generate_authentication_options,
            generate_registration_options,
            options_to_json,
            verify_authentication_response,
            verify_registration_response,
        )
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    except ImportError as exc:
        raise WebAuthnError("WebAuthn support is not installed.") from exc
    return (
        base64url_to_bytes,
        generate_authentication_options,
        generate_registration_options,
        options_to_json,
        verify_authentication_response,
        verify_registration_response,
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )


def registration_options(
    runtime: WebAuthnRuntime,
    *,
    username: str,
    display_name: str,
    opaque_user_handle: bytes,
    challenge: bytes,
    credentials: tuple[WebAuthnCredential, ...],
) -> dict[str, Any]:
    lib = _library()
    options = lib[2](
        rp_id=runtime.rp_id,
        rp_name=runtime.rp_name,
        user_name=username,
        user_display_name=display_name,
        user_id=opaque_user_handle,
        challenge=challenge,
        timeout=300_000,
        authenticator_selection=lib[6](
            resident_key=lib[8].DISCOURAGED,
            user_verification=lib[9].REQUIRED,
        ),
        exclude_credentials=[lib[7](id=item.credential_id) for item in credentials],
    )
    payload = parse_json_document(lib[3](options), policy=_OPTIONS_POLICY)
    if not isinstance(payload, dict):
        raise WebAuthnError("Generated WebAuthn registration options are invalid.")
    return payload


def authentication_options(
    runtime: WebAuthnRuntime,
    *,
    challenge: bytes,
    credentials: tuple[WebAuthnCredential, ...],
) -> dict[str, Any]:
    lib = _library()
    options = lib[1](
        rp_id=runtime.rp_id,
        challenge=challenge,
        timeout=300_000,
        allow_credentials=[lib[7](id=item.credential_id) for item in credentials],
        user_verification=lib[9].REQUIRED,
    )
    payload = parse_json_document(lib[3](options), policy=_OPTIONS_POLICY)
    if not isinstance(payload, dict):
        raise WebAuthnError("Generated WebAuthn authentication options are invalid.")
    return payload


def verify_registration(
    runtime: WebAuthnRuntime,
    *,
    response: dict[str, Any],
    challenge: bytes,
) -> VerifiedRegistration:
    lib = _library()
    try:
        result = lib[5](
            credential=response,
            expected_challenge=challenge,
            expected_rp_id=runtime.rp_id,
            expected_origin=list(runtime.allowed_origins),
            require_user_presence=True,
            require_user_verification=True,
        )
        raw_response = response.get("response", {})
        transports = raw_response.get("transports", []) if isinstance(raw_response, dict) else []
        return VerifiedRegistration(
            credential_id=result.credential_id,
            public_key=result.credential_public_key,
            sign_count=result.sign_count,
            device_type=result.credential_device_type.value,
            backed_up=result.credential_backed_up,
            transports=tuple(str(value) for value in transports),
        )
    except Exception as exc:
        raise WebAuthnError("WebAuthn registration verification failed.") from exc


def credential_id_from_response(response: dict[str, Any]) -> bytes:
    raw_id = response.get("rawId")
    if not isinstance(raw_id, str) or not raw_id or len(raw_id) > 1366:
        raise WebAuthnError("WebAuthn credential identifier is invalid.")
    try:
        return _library()[0](raw_id)
    except Exception as exc:
        raise WebAuthnError("WebAuthn credential identifier is invalid.") from exc


def verify_authentication(
    runtime: WebAuthnRuntime,
    *,
    response: dict[str, Any],
    challenge: bytes,
    credential: WebAuthnCredential,
) -> VerifiedAuthentication:
    lib = _library()
    try:
        result = lib[4](
            credential=response,
            expected_challenge=challenge,
            expected_rp_id=runtime.rp_id,
            expected_origin=list(runtime.allowed_origins),
            credential_public_key=credential.public_key,
            credential_current_sign_count=credential.sign_count,
            require_user_verification=True,
        )
        return VerifiedAuthentication(
            credential_id=credential.credential_id,
            previous_sign_count=credential.sign_count,
            new_sign_count=result.new_sign_count,
            device_type=result.credential_device_type.value,
            backed_up=result.credential_backed_up,
        )
    except Exception as exc:
        raise WebAuthnError("WebAuthn authentication verification failed.") from exc
