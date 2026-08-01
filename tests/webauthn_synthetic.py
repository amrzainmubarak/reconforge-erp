"""Synthetic WebAuthn authenticator responses for end-to-end tests only."""

from __future__ import annotations

import base64
import hashlib
import json

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def client_data(kind: str, challenge: bytes, origin: str) -> bytes:
    return json.dumps(
        {"type": kind, "challenge": b64(challenge), "origin": origin, "crossOrigin": False},
        separators=(",", ":"),
    ).encode()


def registration_response(
    *, challenge: bytes, rp_id: str, origin: str, credential_id: bytes, private_key: ec.EllipticCurvePrivateKey
) -> dict[str, object]:
    numbers = private_key.public_key().public_numbers()
    cose_key = cbor2.dumps(
        {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
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
        "id": b64(credential_id),
        "rawId": b64(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": b64(client_data("webauthn.create", challenge, origin)),
            "attestationObject": b64(attestation),
            "transports": ["internal"],
        },
        "clientExtensionResults": {},
    }


def authentication_response(
    *,
    challenge: bytes,
    rp_id: str,
    origin: str,
    credential_id: bytes,
    private_key: ec.EllipticCurvePrivateKey,
    sign_count: int,
) -> dict[str, object]:
    collected = client_data("webauthn.get", challenge, origin)
    authenticator_data = hashlib.sha256(rp_id.encode()).digest() + bytes([0x05]) + sign_count.to_bytes(4, "big")
    signature = private_key.sign(
        authenticator_data + hashlib.sha256(collected).digest(), ec.ECDSA(hashes.SHA256())
    )
    return {
        "id": b64(credential_id),
        "rawId": b64(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": b64(collected),
            "authenticatorData": b64(authenticator_data),
            "signature": b64(signature),
            "userHandle": None,
        },
        "clientExtensionResults": {},
    }
