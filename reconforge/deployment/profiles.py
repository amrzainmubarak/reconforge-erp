"""Truthful, fail-closed deployment-mode capability contracts.

The profiles are descriptive policy inputs, not a claim that a deployment has
already achieved the listed operational properties.  A caller supplies
runtime facts and receives explicit validation findings before enabling a
mode-sensitive capability.  No network, database, secret, or telemetry call
is made by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

DeploymentEdition = Literal["community", "team", "enterprise", "regulated"]
_EDITIONS: tuple[DeploymentEdition, ...] = ("community", "team", "enterprise", "regulated")


class DeploymentProfileError(ValueError):
    """Raised when an edition or runtime fact is invalid."""


@dataclass(frozen=True)
class DeploymentProfile:
    """Immutable declaration of an edition's safe defaults and requirements."""

    edition: DeploymentEdition
    storage_backend: str
    identity_provider: str
    queue_backend: str
    object_store: str
    network_default: Literal["disabled", "optional", "required"]
    writeback_default: Literal["disabled", "approval_required"]
    supports_air_gap: bool
    requires_customer_managed_keys: bool
    requires_independent_failure_domains: bool
    claim_boundary: str

    def __post_init__(self) -> None:
        if self.edition not in _EDITIONS:
            raise DeploymentProfileError("deployment edition is unsupported")
        for name in (
            "storage_backend",
            "identity_provider",
            "queue_backend",
            "object_store",
            "claim_boundary",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DeploymentProfileError(f"deployment profile {name} is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_boundary": self.claim_boundary,
            "edition": self.edition,
            "identity_provider": self.identity_provider,
            "network_default": self.network_default,
            "object_store": self.object_store,
            "queue_backend": self.queue_backend,
            "requires_customer_managed_keys": self.requires_customer_managed_keys,
            "requires_independent_failure_domains": self.requires_independent_failure_domains,
            "storage_backend": self.storage_backend,
            "supports_air_gap": self.supports_air_gap,
            "writeback_default": self.writeback_default,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class DeploymentRuntimeFacts:
    """Facts observed by an operator before a mode is enabled."""

    storage_backend: str
    identity_provider: str
    queue_backend: str
    object_store: str
    network_enabled: bool = False
    writeback_enabled: bool = False
    human_approval_enabled: bool = False
    air_gap_enabled: bool = False
    customer_managed_keys_enabled: bool = False
    independent_failure_domains_verified: bool = False

    def __post_init__(self) -> None:
        for name in ("storage_backend", "identity_provider", "queue_backend", "object_store"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DeploymentProfileError(f"runtime fact {name} is invalid")
        for name in (
            "network_enabled",
            "writeback_enabled",
            "human_approval_enabled",
            "air_gap_enabled",
            "customer_managed_keys_enabled",
            "independent_failure_domains_verified",
        ):
            if not isinstance(getattr(self, name), bool):
                raise DeploymentProfileError(f"runtime fact {name} must be boolean")


_PROFILES: dict[DeploymentEdition, DeploymentProfile] = {
    "community": DeploymentProfile(
        edition="community",
        storage_backend="sqlite",
        identity_provider="local",
        queue_backend="local",
        object_store="local-files",
        network_default="disabled",
        writeback_default="disabled",
        supports_air_gap=True,
        requires_customer_managed_keys=False,
        requires_independent_failure_domains=False,
        claim_boundary="local-first capability contract; no hosted or production assurance",
    ),
    "team": DeploymentProfile(
        edition="team",
        storage_backend="postgresql",
        identity_provider="local-or-oidc",
        queue_backend="redis",
        object_store="s3-compatible",
        network_default="optional",
        writeback_default="approval_required",
        supports_air_gap=True,
        requires_customer_managed_keys=False,
        requires_independent_failure_domains=False,
        claim_boundary="shared self-hosted capability contract; operational limits remain deployment-specific",
    ),
    "enterprise": DeploymentProfile(
        edition="enterprise",
        storage_backend="postgresql",
        identity_provider="oidc-saml-scim",
        queue_backend="redis-or-durable-queue",
        object_store="s3-compatible",
        network_default="optional",
        writeback_default="approval_required",
        supports_air_gap=True,
        requires_customer_managed_keys=False,
        requires_independent_failure_domains=True,
        claim_boundary="enterprise-oriented controls require deployment and hosted evidence; no readiness claim",
    ),
    "regulated": DeploymentProfile(
        edition="regulated",
        storage_backend="customer-managed-postgresql",
        identity_provider="oidc-saml-scim-mfa",
        queue_backend="ha-durable-queue",
        object_store="worm-compatible-customer-managed",
        network_default="disabled",
        writeback_default="approval_required",
        supports_air_gap=True,
        requires_customer_managed_keys=True,
        requires_independent_failure_domains=True,
        claim_boundary="regulated deployment contract only; independent review and regulatory mapping remain external",
    ),
}


def _edition(value: str) -> DeploymentEdition:
    normalized = str(value).strip().lower()
    if normalized not in _EDITIONS:
        raise DeploymentProfileError("deployment edition is unsupported")
    return normalized


def deployment_profile(edition: str) -> DeploymentProfile:
    """Return the immutable profile for an edition."""

    return _PROFILES[_edition(edition)]


def list_deployment_profiles() -> tuple[DeploymentProfile, ...]:
    """Return profiles in stable edition order."""

    return tuple(_PROFILES[edition] for edition in _EDITIONS)


def validate_deployment_profile(edition: str, facts: DeploymentRuntimeFacts) -> tuple[str, ...]:
    """Return deterministic fail-closed findings for observed runtime facts.

    An empty tuple means the facts are compatible with the profile's declared
    defaults.  It does not grant permission or establish a release claim.
    """

    if not isinstance(facts, DeploymentRuntimeFacts):
        raise DeploymentProfileError("runtime facts are invalid")
    profile = deployment_profile(edition)
    findings: list[str] = []
    if facts.storage_backend != profile.storage_backend:
        findings.append("storage_backend_mismatch")
    if facts.identity_provider != profile.identity_provider:
        findings.append("identity_provider_mismatch")
    if facts.queue_backend != profile.queue_backend:
        findings.append("queue_backend_mismatch")
    if facts.object_store != profile.object_store:
        findings.append("object_store_mismatch")
    if profile.network_default == "disabled" and facts.network_enabled:
        findings.append("network_must_remain_disabled")
    if profile.writeback_default == "disabled" and facts.writeback_enabled:
        findings.append("writeback_must_remain_disabled")
    if facts.writeback_enabled and not facts.human_approval_enabled:
        findings.append("writeback_requires_human_approval")
    if facts.air_gap_enabled and not profile.supports_air_gap:
        findings.append("air_gap_not_supported")
    if profile.requires_customer_managed_keys and not facts.customer_managed_keys_enabled:
        findings.append("customer_managed_keys_required")
    if profile.requires_independent_failure_domains and not facts.independent_failure_domains_verified:
        findings.append("independent_failure_domains_required")
    return tuple(findings)
