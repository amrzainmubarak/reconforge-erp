from __future__ import annotations

import base64
import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from reconforge.auth.webauthn import (
    authentication_options,
    registration_options,
    verify_authentication,
    verify_registration,
)
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.infrastructure.postgres_webauthn import WebAuthnCredential

hashes = pytest.importorskip("cryptography.hazmat.primitives.hashes", reason="webauthn crypto extra is optional")
ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec", reason="webauthn crypto extra is optional")
cbor2 = pytest.importorskip("cbor2", reason="webauthn cbor2 extra is optional")

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client_data(kind: str, challenge: bytes, origin: str) -> bytes:
    return json.dumps(
        {"type": kind, "challenge": _b64(challenge), "origin": origin, "crossOrigin": False},
        separators=(",", ":"),
    ).encode()


def _registration_response(
    *,
    challenge: bytes,
    rp_id: str,
    origin: str,
    credential_id: bytes,
    private_key: EllipticCurvePrivateKey,
) -> dict[str, object]:
    numbers = private_key.public_key().public_numbers()
    cose_key = cbor2.dumps(
        {
            1: 2,
            3: -7,
            -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }
    )
    authenticator_data = (
        hashlib.sha256(rp_id.encode()).digest()
        + bytes([0x45])
        + (0).to_bytes(4, "big")
        + bytes(16)
        + len(credential_id).to_bytes(2, "big")
        + credential_id
        + cose_key
    )
    attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": authenticator_data})
    return {
        "id": _b64(credential_id),
        "rawId": _b64(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64(_client_data("webauthn.create", challenge, origin)),
            "attestationObject": _b64(attestation),
            "transports": ["internal"],
        },
        "clientExtensionResults": {},
    }


def _authentication_response(
    *,
    challenge: bytes,
    rp_id: str,
    origin: str,
    credential_id: bytes,
    private_key: EllipticCurvePrivateKey,
    sign_count: int,
) -> dict[str, object]:
    client_data = _client_data("webauthn.get", challenge, origin)
    authenticator_data = hashlib.sha256(rp_id.encode()).digest() + bytes([0x05]) + sign_count.to_bytes(4, "big")
    signature = private_key.sign(authenticator_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    return {
        "id": _b64(credential_id),
        "rawId": _b64(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64(client_data),
            "authenticatorData": _b64(authenticator_data),
            "signature": _b64(signature),
            "userHandle": None,
        },
        "clientExtensionResults": {},
    }


def test_real_user_verified_webauthn_registration_and_authentication() -> None:
    runtime = WebAuthnRuntime(
        rp_id="example.test",
        rp_name="ReconForge Test",
        allowed_origins=("https://example.test",),
    )
    private_key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"synthetic-credential-id-32bytes!"
    registration_challenge = b"registration-challenge-32-bytes!"
    generated_registration = registration_options(
        runtime,
        username="synthetic-user",
        display_name="Synthetic User",
        opaque_user_handle=hashlib.sha256(b"tenant:user").digest(),
        challenge=registration_challenge,
        credentials=(),
    )
    assert generated_registration["authenticatorSelection"]["userVerification"] == "required"
    registered = verify_registration(
        runtime,
        response=_registration_response(
            challenge=registration_challenge,
            rp_id=runtime.rp_id,
            origin=runtime.allowed_origins[0],
            credential_id=credential_id,
            private_key=private_key,
        ),
        challenge=registration_challenge,
    )
    stored = WebAuthnCredential(
        credential_id=registered.credential_id,
        public_key=registered.public_key,
        sign_count=registered.sign_count,
        transports=registered.transports,
        device_type=registered.device_type,
        backed_up=registered.backed_up,
        label="Synthetic platform authenticator",
    )
    authentication_challenge = b"authentication-challenge-32byte"
    generated_authentication = authentication_options(
        runtime,
        challenge=authentication_challenge,
        credentials=(stored,),
    )
    assert generated_authentication["userVerification"] == "required"
    authenticated = verify_authentication(
        runtime,
        response=_authentication_response(
            challenge=authentication_challenge,
            rp_id=runtime.rp_id,
            origin=runtime.allowed_origins[0],
            credential_id=credential_id,
            private_key=private_key,
            sign_count=1,
        ),
        challenge=authentication_challenge,
        credential=stored,
    )

    assert authenticated.credential_id == credential_id
    assert authenticated.previous_sign_count == 0
    assert authenticated.new_sign_count == 1
