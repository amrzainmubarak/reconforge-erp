"""Provider-neutral enterprise federation application boundary.

Cryptographic and XML/JWT processing is deliberately delegated to reviewed
library adapters. This module owns ReconForge policy, replay, scope, and audit
preconditions and must never parse or verify a token itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FederationError(ValueError):
    """Safe federation failure without provider payload or secret material."""


class _FederationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FederationProvider(_FederationModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    protocol: Literal["oidc", "saml"]
    issuer: str = Field(min_length=1, max_length=2048)
    audiences: tuple[str, ...] = Field(min_length=1, max_length=16)
    allowed_algorithms: tuple[str, ...] = Field(min_length=1, max_length=8)
    group_role_mapping: Mapping[str, str] = Field(default_factory=dict)
    allowed_roles: frozenset[str] = Field(min_length=1, max_length=32)
    enabled: bool = True
    network_required: bool = True

    @field_validator("issuer")
    @classmethod
    def validate_issuer(cls, value: str) -> str:
        if value != value.strip() or any(character.isspace() for character in value):
            raise ValueError("Federation issuer must be an exact non-whitespace value.")
        return value

    @field_validator("audiences", "allowed_algorithms")
    @classmethod
    def validate_exact_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(not value or value != value.strip() for value in values):
            raise ValueError("Federation allowlists must contain unique exact values.")
        return values

    @field_validator("group_role_mapping")
    @classmethod
    def validate_mapping(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        if len(value) > 128 or any(not group or not role or group != group.strip() for group, role in value.items()):
            raise ValueError("Federation group mapping is invalid.")
        return value

    def model_post_init(self, __context: object) -> None:
        if not set(self.group_role_mapping.values()).issubset(self.allowed_roles):
            raise ValueError("Federation role mapping exceeds the provider role allowlist.")
        if "none" in {algorithm.casefold() for algorithm in self.allowed_algorithms}:
            raise ValueError("Unsigned federation assertions are forbidden.")


class FederationRequest(_FederationModel):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    encoded_assertion: str = Field(min_length=1, max_length=2_000_000)
    expected_nonce: str | None = Field(default=None, min_length=16, max_length=256)
    request_id: str | None = Field(default=None, min_length=1, max_length=256)


class VerifiedFederationAssertion(_FederationModel):
    protocol: Literal["oidc", "saml"]
    issuer: str
    subject: str = Field(min_length=1, max_length=512)
    audiences: tuple[str, ...] = Field(min_length=1, max_length=16)
    assertion_id: str = Field(min_length=1, max_length=512)
    issued_at: datetime
    expires_at: datetime
    not_before: datetime | None = None
    nonce: str | None = None
    in_response_to: str | None = None
    groups: tuple[str, ...] = Field(default_factory=tuple, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    signature_verified: bool
    algorithm: str = Field(min_length=1, max_length=64)


class FederatedPrincipal(_FederationModel):
    provider_id: str
    issuer: str
    subject: str
    roles: tuple[str, ...]
    display_name: str | None = None
    email: str | None = None
    assertion_id: str


class FederationVerifier(Protocol):
    """Adapter implemented by reviewed OIDC/SAML libraries."""

    def verify(self, provider: FederationProvider, request: FederationRequest) -> VerifiedFederationAssertion: ...


class FederationReplayStore(Protocol):
    def consume_once(self, *, provider_id: str, assertion_id: str, expires_at: datetime) -> bool: ...


class FederationAuditSink(Protocol):
    def record(self, *, action: str, provider_id: str, outcome: str, reason_code: str | None) -> None: ...


class FederationService:
    """Fail-closed federation policy around library-owned verification."""

    def __init__(
        self,
        *,
        providers: Mapping[str, FederationProvider],
        verifiers: Mapping[str, FederationVerifier],
        replay_store: FederationReplayStore,
        audit_sink: FederationAuditSink,
        air_gap_mode: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock_skew_seconds: int = 60,
    ) -> None:
        if not 0 <= clock_skew_seconds <= 300:
            raise ValueError("Federation clock skew must be between 0 and 300 seconds.")
        self._providers = dict(providers)
        self._verifiers = dict(verifiers)
        self._replay_store = replay_store
        self._audit = audit_sink
        self._air_gap_mode = air_gap_mode
        self._clock = clock
        self._clock_skew_seconds = clock_skew_seconds

    def authenticate(self, request: FederationRequest) -> FederatedPrincipal:
        provider = self._providers.get(request.provider_id)
        if provider is None or not provider.enabled:
            return self._reject(request.provider_id, "provider_unavailable")
        if self._air_gap_mode and provider.network_required:
            return self._reject(provider.id, "federation_disabled_in_air_gap")
        verifier = self._verifiers.get(provider.protocol)
        if verifier is None:
            return self._reject(provider.id, "verifier_unavailable")
        try:
            assertion = verifier.verify(provider, request)
            self._validate_assertion(provider, request, assertion)
            if not self._replay_store.consume_once(
                provider_id=provider.id,
                assertion_id=assertion.assertion_id,
                expires_at=assertion.expires_at,
            ):
                return self._reject(provider.id, "assertion_replayed")
            roles = tuple(
                sorted(
                    {
                        provider.group_role_mapping[group]
                        for group in assertion.groups
                        if group in provider.group_role_mapping
                    }
                )
            )
            if not roles:
                return self._reject(provider.id, "no_allowed_role_mapping")
            principal = FederatedPrincipal(
                provider_id=provider.id,
                issuer=assertion.issuer,
                subject=assertion.subject,
                roles=roles,
                display_name=assertion.display_name,
                email=assertion.email,
                assertion_id=assertion.assertion_id,
            )
            self._audit.record(
                action="federation_authenticate", provider_id=provider.id, outcome="allowed", reason_code=None
            )
            return principal
        except FederationError:
            raise
        except Exception as exc:
            self._audit.record(
                action="federation_authenticate",
                provider_id=provider.id,
                outcome="denied",
                reason_code="verification_failed",
            )
            raise FederationError("Federated authentication failed.") from exc

    def _validate_assertion(
        self,
        provider: FederationProvider,
        request: FederationRequest,
        assertion: VerifiedFederationAssertion,
    ) -> None:
        now = self._clock()
        if now.tzinfo is None or assertion.issued_at.tzinfo is None or assertion.expires_at.tzinfo is None:
            raise FederationError("Federated authentication failed.")
        skew = self._clock_skew_seconds
        if assertion.protocol != provider.protocol or assertion.issuer != provider.issuer:
            raise FederationError("Federated authentication failed.")
        if not assertion.signature_verified or assertion.algorithm not in provider.allowed_algorithms:
            raise FederationError("Federated authentication failed.")
        if not set(assertion.audiences).intersection(provider.audiences):
            raise FederationError("Federated authentication failed.")
        if assertion.expires_at.timestamp() + skew < now.timestamp():
            raise FederationError("Federated authentication failed.")
        if assertion.issued_at.timestamp() - skew > now.timestamp():
            raise FederationError("Federated authentication failed.")
        if assertion.not_before is not None and (
            assertion.not_before.tzinfo is None or assertion.not_before.timestamp() - skew > now.timestamp()
        ):
            raise FederationError("Federated authentication failed.")
        if provider.protocol == "oidc" and (
            request.expected_nonce is None or assertion.nonce != request.expected_nonce
        ):
            raise FederationError("Federated authentication failed.")
        if (
            provider.protocol == "saml"
            and request.request_id is not None
            and assertion.in_response_to != request.request_id
        ):
            raise FederationError("Federated authentication failed.")

    def _reject(self, provider_id: str, reason_code: str) -> FederatedPrincipal:
        self._audit.record(
            action="federation_authenticate",
            provider_id=provider_id,
            outcome="denied",
            reason_code=reason_code,
        )
        raise FederationError("Federated authentication failed.")


class InMemoryFederationReplayStore:
    """Process-local test/community implementation; server deployments need durable storage."""

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._records: dict[tuple[str, str], datetime] = {}

    def consume_once(self, *, provider_id: str, assertion_id: str, expires_at: datetime) -> bool:
        now = self._clock()
        self._records = {key: expiry for key, expiry in self._records.items() if expiry > now}
        key = (provider_id, assertion_id)
        if key in self._records:
            return False
        self._records[key] = expires_at
        return True
