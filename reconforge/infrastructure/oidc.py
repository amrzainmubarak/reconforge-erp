"""OIDC ID Token verification through joserfc and static operator-owned JWKS."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from reconforge.auth.federation import (
    FederationProvider,
    FederationRequest,
    VerifiedFederationAssertion,
)


class OIDCVerificationError(ValueError):
    """Sanitized OIDC verification failure."""


class OIDCStaticJWKSVerifier:
    """Verify signed ID Tokens without discovery or token-controlled URLs."""

    def __init__(self, provider_jwks: Mapping[str, Mapping[str, object]], *, clock_skew_seconds: int = 60) -> None:
        if not 0 <= clock_skew_seconds <= 300:
            raise ValueError("OIDC clock skew must be between 0 and 300 seconds.")
        self._jwks: dict[str, Any] = {
            provider_id: self._validate_jwks(document) for provider_id, document in provider_jwks.items()
        }
        self._clock_skew_seconds = clock_skew_seconds

    def verify(self, provider: FederationProvider, request: FederationRequest) -> VerifiedFederationAssertion:
        if provider.protocol != "oidc" or request.expected_nonce is None:
            raise OIDCVerificationError("OIDC verification failed.")
        key_set = self._jwks.get(provider.id)
        if key_set is None:
            raise OIDCVerificationError("OIDC verification failed.")
        try:
            from joserfc import jwt
            from joserfc.jwt import JWTClaimsRegistry

            token = jwt.decode(
                request.encoded_assertion,
                key_set,
                algorithms=list(provider.allowed_algorithms),
            )
            header = self._mapping(token.header)
            claims = self._mapping(token.claims)
            if "jku" in header or "x5u" in header or not isinstance(header.get("kid"), str):
                raise OIDCVerificationError("OIDC verification failed.")
            registry = JWTClaimsRegistry(
                leeway=self._clock_skew_seconds,
                iss={"essential": True, "value": provider.issuer},
                sub={"essential": True},
                aud={"essential": True, "values": list(provider.audiences)},
                exp={"essential": True},
                iat={"essential": True},
                nonce={"essential": True, "value": request.expected_nonce},
            )
            registry.validate(claims)
            audiences = self._audiences(claims["aud"])
            if len(audiences) > 1 and claims.get("azp") not in provider.audiences:
                raise OIDCVerificationError("OIDC verification failed.")
            groups = self._groups(claims.get("groups", ()))
            issued_at = self._timestamp(claims["iat"])
            expires_at = self._timestamp(claims["exp"])
            not_before = self._timestamp(claims["nbf"]) if "nbf" in claims else None
            algorithm = self._required_text(header, "alg", 64)
            subject = self._required_text(claims, "sub", 512)
            issuer = self._required_text(claims, "iss", 2048)
            nonce = self._required_text(claims, "nonce", 256)
            assertion_id = hashlib.sha256(request.encoded_assertion.encode("ascii")).hexdigest()
            return VerifiedFederationAssertion(
                protocol="oidc",
                issuer=issuer,
                subject=subject,
                audiences=audiences,
                assertion_id=assertion_id,
                issued_at=issued_at,
                expires_at=expires_at,
                not_before=not_before,
                nonce=nonce,
                groups=groups,
                display_name=self._optional_text(claims.get("name"), 256),
                email=self._optional_text(claims.get("email"), 320),
                signature_verified=True,
                algorithm=algorithm,
            )
        except OIDCVerificationError:
            raise
        except Exception as exc:
            raise OIDCVerificationError("OIDC verification failed.") from exc

    @staticmethod
    def _validate_jwks(document: Mapping[str, object]) -> object:
        keys = document.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 32:
            raise ValueError("OIDC JWKS must contain between 1 and 32 public keys.")
        kids: set[str] = set()
        for item in keys:
            if not isinstance(item, dict) or "d" in item:
                raise ValueError("OIDC JWKS must contain public keys only.")
            kid = item.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 256 or kid in kids:
                raise ValueError("OIDC JWKS key IDs must be unique bounded strings.")
            kids.add(kid)
        try:
            from joserfc.jwk import KeySet

            return KeySet.import_key_set(cast(Any, dict(document)))
        except Exception as exc:
            raise ValueError("OIDC JWKS is invalid.") from exc

    @staticmethod
    def _mapping(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise OIDCVerificationError("OIDC verification failed.")
        return value

    @staticmethod
    def _required_text(mapping: Mapping[str, object], key: str, maximum: int) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= maximum:
            raise OIDCVerificationError("OIDC verification failed.")
        return value

    @staticmethod
    def _optional_text(value: object, maximum: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not 1 <= len(value) <= maximum:
            raise OIDCVerificationError("OIDC verification failed.")
        return value

    @staticmethod
    def _audiences(value: object) -> tuple[str, ...]:
        values = (value,) if isinstance(value, str) else tuple(value) if isinstance(value, list) else ()
        if not 1 <= len(values) <= 16 or any(not isinstance(item, str) or not item for item in values):
            raise OIDCVerificationError("OIDC verification failed.")
        return values

    @staticmethod
    def _groups(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or len(value) > 256:
            raise OIDCVerificationError("OIDC verification failed.")
        if any(not isinstance(item, str) or not 1 <= len(item) <= 256 for item in value):
            raise OIDCVerificationError("OIDC verification failed.")
        return tuple(value)

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise OIDCVerificationError("OIDC verification failed.")
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise OIDCVerificationError("OIDC verification failed.") from exc
