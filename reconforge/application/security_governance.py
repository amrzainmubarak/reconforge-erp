"""Backend-neutral contracts for integration and evidence-retention administration."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

IntegrationKind = Literal["federation_link", "notification_route", "scim_credential", "service_account"]
IntegrationStatus = Literal["active", "disabled", "expired"]
DataClassification = Literal["public", "internal", "confidential", "restricted"]

INTEGRATION_KINDS = frozenset({"federation_link", "notification_route", "scim_credential", "service_account"})
DATA_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})
ADMINISTRATION_REASONS = frozenset(
    {"administrative_cleanup", "policy_change", "security_response", "user_request"}
)
RETENTION_ASSIGNMENT_REASONS = frozenset(
    {"policy_application", "regulatory_request", "security_response", "contractual_requirement"}
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,319}$")
_POLICY_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SecurityGovernanceError(ValueError):
    """Safe governance failure carrying one stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class IntegrationSummary:
    kind: IntegrationKind
    id: str
    status: IntegrationStatus
    lifecycle_version: int
    credential_count: int
    active_credential_count: int
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    scope_digest: str
    state_digest: str


@dataclass(frozen=True)
class IntegrationPage:
    items: tuple[IntegrationSummary, ...]
    next_kind: IntegrationKind | None = None
    next_integration_id: str | None = None


@dataclass(frozen=True)
class IntegrationDisableChange:
    integration: IntegrationSummary
    transitioned: bool
    revoked_credentials: int
    audit_event_id: str | None


@dataclass(frozen=True)
class RetentionPolicySummary:
    id: str
    name: str
    description: str
    data_classification: DataClassification
    duration_days: int
    active: bool
    lifecycle_version: int
    created_at: str
    updated_at: str
    retired_at: str | None
    state_digest: str


@dataclass(frozen=True)
class RetentionPolicyPage:
    items: tuple[RetentionPolicySummary, ...]
    next_name: str | None = None
    next_policy_id: str | None = None


@dataclass(frozen=True)
class RetentionPolicyChange:
    policy: RetentionPolicySummary
    transitioned: bool
    audit_event_id: str | None


@dataclass(frozen=True)
class EvidenceRetentionChange:
    evidence_id: str
    policy_id: str
    policy_lifecycle_version: int
    retention_version: int
    previous_retention_until: str | None
    policy_retention_until: str
    effective_retention_until: str
    retention_extended: bool
    transitioned: bool
    audit_event_id: str | None
    state_digest: str


class SecurityGovernanceRepository(Protocol):
    def list_integrations(
        self,
        *,
        as_of: datetime,
        include_inactive: bool,
        limit: int,
        after_kind: IntegrationKind | None,
        after_integration_id: str | None,
    ) -> IntegrationPage: ...

    def disable_integration(
        self,
        *,
        actor_user_id: str,
        kind: IntegrationKind,
        integration_id: str,
        expected_state_digest: str,
        reason_code: str,
        as_of: datetime,
    ) -> IntegrationDisableChange: ...

    def list_retention_policies(
        self,
        *,
        include_retired: bool,
        limit: int,
        after_name: str | None,
        after_policy_id: str | None,
    ) -> RetentionPolicyPage: ...

    def create_retention_policy(
        self,
        *,
        actor_user_id: str,
        name: str,
        description: str,
        data_classification: DataClassification,
        duration_days: int,
        as_of: datetime,
    ) -> RetentionPolicyChange: ...

    def update_retention_policy(
        self,
        *,
        actor_user_id: str,
        policy_id: str,
        description: str | None,
        data_classification: DataClassification | None,
        duration_days: int | None,
        active: bool | None,
        expected_lifecycle_version: int,
        reason_code: str,
        as_of: datetime,
    ) -> RetentionPolicyChange: ...

    def apply_retention_policy(
        self,
        *,
        actor_user_id: str,
        policy_id: str,
        evidence_id: str,
        expected_retention_version: int,
        reason_code: str,
        as_of: datetime,
    ) -> EvidenceRetentionChange: ...


def _identifier(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise SecurityGovernanceError("security_governance_identifier_invalid", f"{field_name} is invalid.")
    return normalized


def _policy_name(value: str) -> str:
    normalized = str(value).strip().casefold()
    if not _POLICY_NAME.fullmatch(normalized):
        raise SecurityGovernanceError(
            "retention_policy_name_invalid", "name must be a lowercase policy identifier."
        )
    return normalized


def _description(value: str) -> str:
    normalized = str(value).strip()
    if len(normalized) > 500 or any(ord(character) < 32 and character not in "\t\n" for character in normalized):
        raise SecurityGovernanceError(
            "retention_policy_description_invalid", "description is invalid or exceeds 500 characters."
        )
    return normalized


def _classification(value: str) -> DataClassification:
    normalized = str(value).strip().casefold()
    if normalized not in DATA_CLASSIFICATIONS:
        raise SecurityGovernanceError(
            "retention_policy_classification_invalid", "data_classification is unsupported."
        )
    return normalized  # type: ignore[return-value]


def _duration(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 36_500:
        raise SecurityGovernanceError(
            "retention_policy_duration_invalid", "duration_days must be between 1 and 36500."
        )
    return value


def _version(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SecurityGovernanceError(
            "security_governance_version_invalid", f"{field_name} must be a positive integer."
        )
    return value


def _digest(value: str) -> str:
    normalized = str(value).strip().casefold()
    if not _SHA256.fullmatch(normalized):
        raise SecurityGovernanceError(
            "integration_state_digest_invalid", "expected_state_digest must be a lowercase SHA-256 digest."
        )
    return normalized


def _reason(value: str, allowed: frozenset[str], code: str) -> str:
    normalized = str(value).strip().casefold()
    if normalized not in allowed:
        raise SecurityGovernanceError(code, "reason_code is unsupported.")
    return normalized


def _kind(value: str) -> IntegrationKind:
    normalized = str(value).strip().casefold()
    if normalized not in INTEGRATION_KINDS:
        raise SecurityGovernanceError("integration_kind_invalid", "Integration kind is unsupported.")
    return normalized  # type: ignore[return-value]


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200:
        raise SecurityGovernanceError("security_governance_page_limit_invalid", "limit must be between 1 and 200.")
    return value


def _utc_second(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SecurityGovernanceError("security_governance_time_invalid", "Administration time needs a timezone.")
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise SecurityGovernanceError(
            "security_governance_time_invalid", "Administration time must use whole-second precision."
        )
    return normalized


def _paired(left: str | None, right: str | None, code: str) -> tuple[str | None, str | None]:
    if (left is None) != (right is None):
        raise SecurityGovernanceError(code, "Pagination boundary fields must be supplied together.")
    return left, right


class SecurityGovernanceApplicationService:
    """Validate privileged governance operations before any repository effect."""

    def __init__(self, repository: SecurityGovernanceRepository, *, clock: Callable[[], datetime]) -> None:
        self.repository = repository
        self.clock = clock

    def list_integrations(
        self,
        *,
        include_inactive: bool = False,
        limit: int = 100,
        after_kind: str | None = None,
        after_integration_id: str | None = None,
    ) -> IntegrationPage:
        if not isinstance(include_inactive, bool):
            raise SecurityGovernanceError("integration_filter_invalid", "include_inactive must be a boolean.")
        after_kind, after_integration_id = _paired(
            after_kind, after_integration_id, "integration_cursor_invalid"
        )
        return self.repository.list_integrations(
            as_of=_utc_second(self.clock()),
            include_inactive=include_inactive,
            limit=_limit(limit),
            after_kind=None if after_kind is None else _kind(after_kind),
            after_integration_id=None
            if after_integration_id is None
            else _identifier(after_integration_id, "after_integration_id"),
        )

    def disable_integration(
        self,
        *,
        actor_user_id: str,
        kind: str,
        integration_id: str,
        expected_state_digest: str,
        reason_code: str,
    ) -> IntegrationDisableChange:
        return self.repository.disable_integration(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            kind=_kind(kind),
            integration_id=_identifier(integration_id, "integration_id"),
            expected_state_digest=_digest(expected_state_digest),
            reason_code=_reason(reason_code, ADMINISTRATION_REASONS, "integration_disable_reason_invalid"),
            as_of=_utc_second(self.clock()),
        )

    def list_retention_policies(
        self,
        *,
        include_retired: bool = False,
        limit: int = 100,
        after_name: str | None = None,
        after_policy_id: str | None = None,
    ) -> RetentionPolicyPage:
        if not isinstance(include_retired, bool):
            raise SecurityGovernanceError("retention_policy_filter_invalid", "include_retired must be a boolean.")
        after_name, after_policy_id = _paired(after_name, after_policy_id, "retention_policy_cursor_invalid")
        return self.repository.list_retention_policies(
            include_retired=include_retired,
            limit=_limit(limit),
            after_name=None if after_name is None else _policy_name(after_name),
            after_policy_id=None
            if after_policy_id is None
            else _identifier(after_policy_id, "after_policy_id"),
        )

    def create_retention_policy(
        self,
        *,
        actor_user_id: str,
        name: str,
        description: str,
        data_classification: str,
        duration_days: int,
    ) -> RetentionPolicyChange:
        return self.repository.create_retention_policy(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            name=_policy_name(name),
            description=_description(description),
            data_classification=_classification(data_classification),
            duration_days=_duration(duration_days),
            as_of=_utc_second(self.clock()),
        )

    def update_retention_policy(
        self,
        *,
        actor_user_id: str,
        policy_id: str,
        expected_lifecycle_version: int,
        reason_code: str,
        description: str | None = None,
        data_classification: str | None = None,
        duration_days: int | None = None,
        active: bool | None = None,
    ) -> RetentionPolicyChange:
        if active is not None and not isinstance(active, bool):
            raise SecurityGovernanceError("retention_policy_status_invalid", "active must be a boolean.")
        if all(value is None for value in (description, data_classification, duration_days, active)):
            raise SecurityGovernanceError("retention_policy_update_empty", "At least one policy field is required.")
        return self.repository.update_retention_policy(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            policy_id=_identifier(policy_id, "policy_id"),
            description=None if description is None else _description(description),
            data_classification=None if data_classification is None else _classification(data_classification),
            duration_days=None if duration_days is None else _duration(duration_days),
            active=active,
            expected_lifecycle_version=_version(expected_lifecycle_version, "expected_lifecycle_version"),
            reason_code=_reason(reason_code, ADMINISTRATION_REASONS, "retention_policy_reason_invalid"),
            as_of=_utc_second(self.clock()),
        )

    def apply_retention_policy(
        self,
        *,
        actor_user_id: str,
        policy_id: str,
        evidence_id: str,
        expected_retention_version: int,
        reason_code: str,
    ) -> EvidenceRetentionChange:
        return self.repository.apply_retention_policy(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            policy_id=_identifier(policy_id, "policy_id"),
            evidence_id=_identifier(evidence_id, "evidence_id"),
            expected_retention_version=_version(expected_retention_version, "expected_retention_version"),
            reason_code=_reason(
                reason_code, RETENTION_ASSIGNMENT_REASONS, "retention_assignment_reason_invalid"
            ),
            as_of=_utc_second(self.clock()),
        )


def canonical_policy_names(values: Sequence[str]) -> tuple[str, ...]:
    """Return an exact stable policy-name set for callers that compose policy batches."""

    normalized = tuple(sorted(_policy_name(value) for value in values))
    if len(set(normalized)) != len(normalized):
        raise SecurityGovernanceError("retention_policy_names_duplicate", "Policy names must be unique.")
    return normalized
