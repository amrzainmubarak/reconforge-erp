from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from reconforge.auth.federation import (
    FederationError,
    FederationProvider,
    FederationRequest,
    FederationService,
    InMemoryFederationReplayStore,
    VerifiedFederationAssertion,
)

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


class Verifier:
    def __init__(self, assertion: VerifiedFederationAssertion | None = None, *, fail: bool = False) -> None:
        self.assertion = assertion or _assertion()
        self.fail = fail

    def verify(self, provider: FederationProvider, request: FederationRequest) -> VerifiedFederationAssertion:
        del provider, request
        if self.fail:
            raise RuntimeError("secret provider detail")
        return self.assertion


class Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, str | None]] = []

    def record(self, *, action: str, provider_id: str, outcome: str, reason_code: str | None) -> None:
        self.events.append(
            {"action": action, "provider_id": provider_id, "outcome": outcome, "reason_code": reason_code}
        )


def _provider(protocol: Literal["oidc", "saml"] = "oidc") -> FederationProvider:
    return FederationProvider(
        id=f"corp-{protocol}",
        protocol=protocol,
        issuer=f"https://id.example/{protocol}",
        audiences=("reconforge-team",),
        allowed_algorithms=("RS256",),
        group_role_mapping={"finance-reviewers": "reviewer", "finance-admins": "admin"},
        allowed_roles=frozenset({"reviewer", "admin"}),
    )


def _assertion(**changes: object) -> VerifiedFederationAssertion:
    values: dict[str, object] = {
        "protocol": "oidc",
        "issuer": "https://id.example/oidc",
        "subject": "user-123",
        "audiences": ("reconforge-team",),
        "assertion_id": "assertion-123",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "nonce": "nonce-0123456789abcdef",
        "groups": ("finance-reviewers", "ignored-external-admin"),
        "signature_verified": True,
        "algorithm": "RS256",
    }
    values.update(changes)
    return VerifiedFederationAssertion.model_validate(values)


def _service(provider: FederationProvider, verifier: Verifier, audit: Audit, *, air_gap: bool = False) -> FederationService:
    return FederationService(
        providers={provider.id: provider},
        verifiers={provider.protocol: verifier},
        replay_store=InMemoryFederationReplayStore(clock=lambda: NOW),
        audit_sink=audit,
        air_gap_mode=air_gap,
        clock=lambda: NOW,
    )


def _request(provider: FederationProvider) -> FederationRequest:
    return FederationRequest(
        provider_id=provider.id,
        encoded_assertion="library-owned-token",
        expected_nonce="nonce-0123456789abcdef" if provider.protocol == "oidc" else None,
        request_id="request-123" if provider.protocol == "saml" else None,
    )


def test_oidc_policy_maps_only_allowlisted_roles_and_audits_without_claims() -> None:
    provider = _provider()
    audit = Audit()
    principal = _service(provider, Verifier(), audit).authenticate(_request(provider))

    assert principal.subject == "user-123"
    assert principal.roles == ("reviewer",)
    assert audit.events == [
        {"action": "federation_authenticate", "provider_id": "corp-oidc", "outcome": "allowed", "reason_code": None}
    ]


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("issuer", "https://evil.example"),
        ("audiences", ("different-client",)),
        ("signature_verified", False),
        ("algorithm", "HS256"),
        ("nonce", "different-nonce"),
        ("expires_at", NOW - timedelta(minutes=2)),
        ("issued_at", NOW + timedelta(minutes=2)),
        ("not_before", NOW + timedelta(minutes=2)),
    ],
)
def test_oidc_policy_fails_closed_for_invalid_security_claims(change: str, value: object) -> None:
    provider = _provider()
    with pytest.raises(FederationError, match="^Federated authentication failed\\.$"):
        _service(provider, Verifier(_assertion(**{change: value})), Audit()).authenticate(_request(provider))


def test_assertion_replay_is_denied_and_recorded() -> None:
    provider = _provider()
    audit = Audit()
    replay = InMemoryFederationReplayStore(clock=lambda: NOW)
    service = FederationService(
        providers={provider.id: provider},
        verifiers={"oidc": Verifier()},
        replay_store=replay,
        audit_sink=audit,
        clock=lambda: NOW,
    )
    service.authenticate(_request(provider))
    with pytest.raises(FederationError):
        service.authenticate(_request(provider))
    assert audit.events[-1]["reason_code"] == "assertion_replayed"


def test_saml_request_correlation_is_mandatory_when_request_id_exists() -> None:
    provider = _provider("saml")
    valid = _assertion(
        protocol="saml",
        issuer=provider.issuer,
        nonce=None,
        in_response_to="request-123",
    )
    assert _service(provider, Verifier(valid), Audit()).authenticate(_request(provider)).roles == ("reviewer",)
    invalid = valid.model_copy(update={"in_response_to": "other-request", "assertion_id": "assertion-456"})
    with pytest.raises(FederationError):
        _service(provider, Verifier(invalid), Audit()).authenticate(_request(provider))


def test_air_gap_and_library_failure_are_sanitized_and_audited() -> None:
    provider = _provider()
    audit = Audit()
    with pytest.raises(FederationError, match="^Federated authentication failed\\.$"):
        _service(provider, Verifier(), audit, air_gap=True).authenticate(_request(provider))
    assert audit.events[-1]["reason_code"] == "federation_disabled_in_air_gap"

    failure_audit = Audit()
    with pytest.raises(FederationError, match="^Federated authentication failed\\.$") as captured:
        _service(provider, Verifier(fail=True), failure_audit).authenticate(_request(provider))
    assert "secret provider detail" not in str(captured.value)
    assert failure_audit.events[-1]["reason_code"] == "verification_failed"


def test_provider_configuration_forbids_unsigned_or_overgranting_mapping() -> None:
    with pytest.raises(ValueError, match="Unsigned"):
        FederationProvider.model_validate(_provider().model_dump() | {"allowed_algorithms": ("none",)})
    with pytest.raises(ValueError, match="exceeds"):
        FederationProvider(
            id="bad-mapping",
            protocol="oidc",
            issuer="https://id.example",
            audiences=("client",),
            allowed_algorithms=("RS256",),
            group_role_mapping={"external-superuser": "superuser"},
            allowed_roles=frozenset({"reviewer"}),
        )
