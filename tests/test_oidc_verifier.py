from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from reconforge.auth.federation import FederationProvider, FederationRequest
from reconforge.infrastructure.oidc import OIDCStaticJWKSVerifier, OIDCVerificationError


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _keys() -> tuple[Any, dict[str, Any]]:
    from joserfc.jwk import RSAKey

    private = RSAKey.generate_key(2048, parameters={"kid": "test-rsa-1", "use": "sig", "alg": "RS256"})
    return private, {"keys": [private.as_dict(private=False)]}


def _provider() -> FederationProvider:
    return FederationProvider(
        id="corp-oidc",
        protocol="oidc",
        issuer="https://id.example/oidc",
        audiences=("reconforge-team",),
        allowed_algorithms=("RS256",),
        group_role_mapping={"finance-reviewers": "reviewer"},
        allowed_roles=frozenset({"reviewer"}),
    )


def _token(private: Any, **changes: object) -> str:
    from joserfc import jwt

    now = _now()
    claims: dict[str, object] = {
        "iss": "https://id.example/oidc",
        "sub": "user-123",
        "aud": "reconforge-team",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "nonce-0123456789abcdef",
        "groups": ["finance-reviewers"],
        "name": "Finance Reviewer",
        "email": "reviewer@example.test",
    }
    claims.update(changes)
    return jwt.encode({"alg": "RS256", "kid": "test-rsa-1", "typ": "JWT"}, claims, private, algorithms=["RS256"])


def _request(token: str) -> FederationRequest:
    return FederationRequest(
        provider_id="corp-oidc",
        encoded_assertion=token,
        expected_nonce="nonce-0123456789abcdef",
    )


def test_real_rsa_signed_oidc_token_is_verified_and_normalized() -> None:
    private, jwks = _keys()
    assertion = OIDCStaticJWKSVerifier({"corp-oidc": jwks}).verify(_provider(), _request(_token(private)))

    assert assertion.signature_verified is True
    assert assertion.algorithm == "RS256"
    assert assertion.subject == "user-123"
    assert assertion.audiences == ("reconforge-team",)
    assert assertion.groups == ("finance-reviewers",)
    assert len(assertion.assertion_id) == 64


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("iss", "https://evil.example"),
        ("aud", "other-client"),
        ("nonce", "wrong-nonce"),
        ("exp", "expired-at-execution"),
        ("iat", "future-at-execution"),
    ],
)
def test_real_oidc_token_rejects_invalid_required_claims(change: str, value: object) -> None:
    private, jwks = _keys()
    now = _now()
    if value == "expired-at-execution":
        value = int((now - timedelta(minutes=2)).timestamp())
    elif value == "future-at-execution":
        value = int((now + timedelta(minutes=2)).timestamp())
    with pytest.raises(OIDCVerificationError, match="^OIDC verification failed\\.$"):
        OIDCStaticJWKSVerifier({"corp-oidc": jwks}).verify(_provider(), _request(_token(private, **{change: value})))


def test_signature_key_and_algorithm_confusion_fail_closed() -> None:
    private, jwks = _keys()
    other_private, _ = _keys()
    verifier = OIDCStaticJWKSVerifier({"corp-oidc": jwks})
    with pytest.raises(OIDCVerificationError):
        verifier.verify(_provider(), _request(_token(other_private)))

    from joserfc import jwt
    from joserfc.jwk import OctKey

    symmetric = OctKey.import_key(b"a" * 32, parameters={"kid": "test-rsa-1"})
    now = _now()
    claims = {
        "iss": _provider().issuer,
        "sub": "user-123",
        "aud": "reconforge-team",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "nonce-0123456789abcdef",
        "groups": ["finance-reviewers"],
    }
    confused = jwt.encode({"alg": "HS256", "kid": "test-rsa-1"}, claims, symmetric, algorithms=["HS256"])
    with pytest.raises(OIDCVerificationError):
        verifier.verify(_provider(), _request(confused))


def test_multiple_audiences_require_allowed_authorized_party() -> None:
    private, jwks = _keys()
    verifier = OIDCStaticJWKSVerifier({"corp-oidc": jwks})
    invalid = _token(private, aud=["reconforge-team", "other"], azp="other")
    with pytest.raises(OIDCVerificationError):
        verifier.verify(_provider(), _request(invalid))
    valid = _token(private, aud=["reconforge-team", "other"], azp="reconforge-team")
    assert verifier.verify(_provider(), _request(valid)).subject == "user-123"


def test_token_controlled_key_urls_and_private_or_duplicate_jwks_are_rejected() -> None:
    private, jwks = _keys()
    from joserfc import jwt

    now = _now()
    claims = {
        "iss": _provider().issuer,
        "sub": "user-123",
        "aud": "reconforge-team",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "nonce-0123456789abcdef",
        "groups": ["finance-reviewers"],
    }
    malicious = jwt.encode(
        {"alg": "RS256", "kid": "test-rsa-1", "jku": "https://evil.example/jwks"},
        claims,
        private,
        algorithms=["RS256"],
    )
    with pytest.raises(OIDCVerificationError):
        OIDCStaticJWKSVerifier({"corp-oidc": jwks}).verify(_provider(), _request(malicious))

    private_jwk = private.as_dict(private=True)
    with pytest.raises(ValueError, match="public keys only"):
        OIDCStaticJWKSVerifier({"corp-oidc": {"keys": [private_jwk]}})
    with pytest.raises(ValueError, match="unique"):
        OIDCStaticJWKSVerifier({"corp-oidc": {"keys": [jwks["keys"][0], jwks["keys"][0]]}})
