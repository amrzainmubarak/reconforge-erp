"""Typed, replayable temporary-delegation records for local policy administration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


class DelegationValidationError(ValueError):
    """Raised when a delegation violates the local policy contract."""


@dataclass(frozen=True)
class DelegationGrant:
    """An approved, time-bounded grant; timestamps must be timezone-aware."""

    id: str
    tenant_id: str
    workspace_id: str
    delegator_id: str
    delegatee_id: str
    permissions: frozenset[str]
    starts_at: datetime
    expires_at: datetime
    created_by: str
    approved_by: str
    status: str = "active"
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("starts_at", "expires_at", "revoked_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise DelegationValidationError(f"{field_name} must be timezone-aware")
        required = (self.id, self.tenant_id, self.workspace_id, self.delegator_id, self.delegatee_id, self.created_by, self.approved_by)
        if any(not value.strip() for value in required):
            raise DelegationValidationError("delegation identity fields are required")
        if self.delegator_id.casefold() == self.delegatee_id.casefold():
            raise DelegationValidationError("delegator and delegatee must be distinct")
        if not self.permissions or any(not permission.strip() for permission in self.permissions):
            raise DelegationValidationError("delegation must contain non-empty permissions")
        if self.starts_at >= self.expires_at:
            raise DelegationValidationError("delegation expiry must be after its start")
        if self.approved_by.casefold() == self.delegator_id.casefold():
            raise DelegationValidationError("delegation approval requires an independent actor")
        if self.status not in {"active", "revoked"}:
            raise DelegationValidationError("delegation status is invalid")
        if self.status == "revoked" and (self.revoked_at is None or not self.revoked_by or not self.revoked_by.strip()):
            raise DelegationValidationError("revoked delegation requires actor and timestamp")
        if self.status == "active" and (self.revoked_at is not None or self.revoked_by is not None):
            raise DelegationValidationError("active delegation cannot contain revocation metadata")

    def is_effective_at(self, evaluation_time: datetime) -> bool:
        """Return whether this grant is active at an explicit replay instant."""

        if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
            raise DelegationValidationError("evaluation_time must be timezone-aware")
        return self.status == "active" and self.starts_at <= evaluation_time < self.expires_at

    def permissions_json(self) -> str:
        return json.dumps(sorted(self.permissions), ensure_ascii=True, separators=(",", ":"))
