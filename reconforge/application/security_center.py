"""Disclosure-bounded administration and security overview contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

_SCOPE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_CLAIM_BOUNDARY = "operational_snapshot_not_security_assurance"


class SecurityCenterError(ValueError):
    """Raised when a security overview cannot be produced safely."""


@dataclass(frozen=True)
class SecurityCenterCounts:
    """Tenant-scoped counts only; no subject, credential, destination, or financial data."""

    total_users: int = 0
    active_users: int = 0
    disabled_users: int = 0
    locked_users: int = 0
    active_users_without_roles: int = 0
    roles: int = 0
    permissions: int = 0
    role_permission_bindings: int = 0
    active_sessions: int = 0
    revoked_sessions: int = 0
    expired_unrevoked_sessions: int = 0
    active_step_up_assertions: int = 0
    active_webauthn_credentials: int = 0
    users_with_active_webauthn: int = 0
    linked_federation_providers: int = 0
    active_federation_links: int = 0
    disabled_federation_links: int = 0
    scim_domains: int = 0
    active_scim_users: int = 0
    active_scim_credentials: int = 0
    enabled_service_accounts: int = 0
    active_service_account_credentials: int = 0
    enabled_notification_routes: int = 0
    active_scope_grants: int = 0
    pending_emergency_requests: int = 0
    active_emergency_access: int = 0
    overdue_emergency_reviews: int = 0
    evidence_records: int = 0
    evidence_with_retention: int = 0
    evidence_retention_expired: int = 0
    evidence_unverified: int = 0
    evidence_verification_failed: int = 0
    audit_events: int = 0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SecurityCenterError(f"{name} must be a non-negative integer.")
        if self.active_users + self.disabled_users != self.total_users:
            raise SecurityCenterError("Active and disabled users must equal total users.")
        if self.locked_users > self.active_users:
            raise SecurityCenterError("Locked users cannot exceed active users.")
        if self.active_users_without_roles > self.active_users:
            raise SecurityCenterError("Users without roles cannot exceed active users.")
        if self.users_with_active_webauthn > self.active_users:
            raise SecurityCenterError("WebAuthn-enrolled users cannot exceed active users.")
        if self.evidence_with_retention > self.evidence_records:
            raise SecurityCenterError("Retained evidence cannot exceed evidence records.")
        if self.evidence_retention_expired > self.evidence_with_retention:
            raise SecurityCenterError("Expired retention cannot exceed retained evidence.")


@dataclass(frozen=True)
class SecurityCenterRuntime:
    """Non-secret runtime feature state supplied by the trusted composition root."""

    configured_federation_providers: int = 0
    federation_air_gap_mode: bool = False
    webauthn_required_for_privileged_actions: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.configured_federation_providers, bool)
            or not isinstance(self.configured_federation_providers, int)
            or self.configured_federation_providers < 0
        ):
            raise SecurityCenterError("configured_federation_providers must be a non-negative integer.")


@dataclass(frozen=True, order=True)
class SecurityAttentionItem:
    severity: str
    code: str
    count: int


@dataclass(frozen=True)
class SecurityCenterSnapshot:
    schema_version: int
    as_of: str
    tenant_scope_digest: str
    posture: str
    claim_boundary: str
    identity: dict[str, int]
    sessions: dict[str, int]
    integrations: dict[str, int | bool]
    policy: dict[str, int]
    retention: dict[str, int]
    audit: dict[str, int | str]
    attention_items: tuple[SecurityAttentionItem, ...]
    snapshot_digest: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of,
            "tenant_scope_digest": self.tenant_scope_digest,
            "posture": self.posture,
            "claim_boundary": self.claim_boundary,
            "identity": dict(self.identity),
            "sessions": dict(self.sessions),
            "integrations": dict(self.integrations),
            "policy": dict(self.policy),
            "retention": dict(self.retention),
            "audit": dict(self.audit),
            "attention_items": [asdict(item) for item in self.attention_items],
            "snapshot_digest": self.snapshot_digest,
        }


class SecurityCenterRepository(Protocol):
    def read_counts(self, *, tenant_id: str, as_of: datetime) -> SecurityCenterCounts: ...


def _utc_second(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SecurityCenterError("Security overview time must include a timezone.")
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise SecurityCenterError("Security overview time must use whole-second precision.")
    return normalized


def _attention(counts: SecurityCenterCounts, runtime: SecurityCenterRuntime) -> tuple[SecurityAttentionItem, ...]:
    items: list[SecurityAttentionItem] = []
    candidates = (
        ("high", "active_users_without_roles", counts.active_users_without_roles),
        ("high", "locked_users", counts.locked_users),
        ("medium", "expired_unrevoked_sessions", counts.expired_unrevoked_sessions),
        ("high", "overdue_emergency_reviews", counts.overdue_emergency_reviews),
        ("medium", "evidence_without_retention", counts.evidence_records - counts.evidence_with_retention),
        ("high", "evidence_verification_failed", counts.evidence_verification_failed),
        ("medium", "evidence_unverified", counts.evidence_unverified),
    )
    for severity, code, count in candidates:
        if count:
            items.append(SecurityAttentionItem(severity=severity, code=code, count=count))
    if runtime.webauthn_required_for_privileged_actions:
        enrollment_gap = counts.active_users - counts.users_with_active_webauthn
        if enrollment_gap:
            items.append(SecurityAttentionItem("high", "privileged_mfa_enrollment_gap", enrollment_gap))
    return tuple(sorted(items))


class SecurityCenterApplicationService:
    """Build one deterministic, tenant-bound, disclosure-safe operational snapshot."""

    def __init__(self, repository: SecurityCenterRepository, *, clock: Callable[[], datetime]) -> None:
        self.repository = repository
        self.clock = clock

    def snapshot(self, *, tenant_id: str, runtime: SecurityCenterRuntime) -> SecurityCenterSnapshot:
        tenant = str(tenant_id).strip().casefold()
        if not _SCOPE.fullmatch(tenant):
            raise SecurityCenterError("tenant_id is invalid.")
        as_of = _utc_second(self.clock())
        counts = self.repository.read_counts(tenant_id=tenant, as_of=as_of)
        attention = _attention(counts, runtime)
        identity = {
            "total_users": counts.total_users,
            "active_users": counts.active_users,
            "disabled_users": counts.disabled_users,
            "locked_users": counts.locked_users,
            "active_users_without_roles": counts.active_users_without_roles,
            "roles": counts.roles,
            "permissions": counts.permissions,
            "role_permission_bindings": counts.role_permission_bindings,
        }
        sessions = {
            "active_sessions": counts.active_sessions,
            "revoked_sessions": counts.revoked_sessions,
            "expired_unrevoked_sessions": counts.expired_unrevoked_sessions,
            "active_step_up_assertions": counts.active_step_up_assertions,
            "active_webauthn_credentials": counts.active_webauthn_credentials,
            "users_with_active_webauthn": counts.users_with_active_webauthn,
        }
        integrations: dict[str, int | bool] = {
            "configured_federation_providers": runtime.configured_federation_providers,
            "federation_air_gap_mode": runtime.federation_air_gap_mode,
            "linked_federation_providers": counts.linked_federation_providers,
            "active_federation_links": counts.active_federation_links,
            "disabled_federation_links": counts.disabled_federation_links,
            "scim_domains": counts.scim_domains,
            "active_scim_users": counts.active_scim_users,
            "active_scim_credentials": counts.active_scim_credentials,
            "enabled_service_accounts": counts.enabled_service_accounts,
            "active_service_account_credentials": counts.active_service_account_credentials,
            "enabled_notification_routes": counts.enabled_notification_routes,
            "webauthn_required_for_privileged_actions": runtime.webauthn_required_for_privileged_actions,
        }
        policy = {
            "active_scope_grants": counts.active_scope_grants,
            "pending_emergency_requests": counts.pending_emergency_requests,
            "active_emergency_access": counts.active_emergency_access,
            "overdue_emergency_reviews": counts.overdue_emergency_reviews,
        }
        retention = {
            "evidence_records": counts.evidence_records,
            "evidence_with_retention": counts.evidence_with_retention,
            "evidence_retention_expired": counts.evidence_retention_expired,
            "evidence_unverified": counts.evidence_unverified,
            "evidence_verification_failed": counts.evidence_verification_failed,
        }
        audit: dict[str, int | str] = {
            "audit_events": counts.audit_events,
            "chain_verification": "not_evaluated_use_audit_verify_endpoint",
        }
        body: dict[str, object] = {
            "schema_version": 1,
            "as_of": as_of.isoformat().replace("+00:00", "Z"),
            "tenant_scope_digest": hashlib.sha256(tenant.encode("utf-8")).hexdigest(),
            "posture": "attention_required" if attention else "observed_no_count_based_attention",
            "claim_boundary": _CLAIM_BOUNDARY,
            "identity": identity,
            "sessions": sessions,
            "integrations": integrations,
            "policy": policy,
            "retention": retention,
            "audit": audit,
            "attention_items": [asdict(item) for item in attention],
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        return SecurityCenterSnapshot(
            schema_version=1,
            as_of=str(body["as_of"]),
            tenant_scope_digest=str(body["tenant_scope_digest"]),
            posture=str(body["posture"]),
            claim_boundary=_CLAIM_BOUNDARY,
            identity=identity,
            sessions=sessions,
            integrations=integrations,
            policy=policy,
            retention=retention,
            audit=audit,
            attention_items=attention,
            snapshot_digest=digest,
        )
