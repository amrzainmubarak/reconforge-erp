"""Provider-neutral SCIM 2.0 provisioning application boundary.

The boundary deliberately models provisioning data, not authorization.  SCIM
groups can be synchronized without granting ReconForge roles or permissions.
HTTP authentication, persistence, and protocol response rendering belong to
adapters layered above and below this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._@+-]{0,159}$")


class SCIMError(ValueError):
    """A disclosure-safe SCIM application error."""

    def __init__(self, message: str, *, scim_type: str = "invalidValue") -> None:
        super().__init__(message)
        self.scim_type = scim_type


def _clean(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain 1 to {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field} must contain printable characters only.")
    return " ".join(normalized.split())


def _scope(value: str, field: str) -> str:
    normalized = _clean(value, field, 64).casefold()
    if not _ID.fullmatch(normalized):
        raise SCIMError(f"{field} has an invalid identifier.")
    return normalized


class SCIMName(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    formatted: str | None = Field(default=None, max_length=255)
    givenName: str | None = Field(default=None, max_length=128)
    familyName: str | None = Field(default=None, max_length=128)

    @field_validator("formatted", "givenName", "familyName")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value, "name", 255)


class SCIMEmail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str = Field(max_length=320)
    type: Literal["work", "home", "other"] = "work"
    primary: bool = False

    @field_validator("value")
    @classmethod
    def clean_email(cls, value: str) -> str:
        normalized = _clean(value, "email", 320).casefold()
        if normalized.count("@") != 1:
            raise ValueError("email must be a bounded address.")
        return normalized


class SCIMUserWrite(BaseModel):
    """Supported, closed subset of the RFC 7643 User write schema."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schemas: tuple[str, ...]
    externalId: str = Field(min_length=1, max_length=255)
    userName: str = Field(min_length=1, max_length=160)
    name: SCIMName | None = None
    displayName: str | None = Field(default=None, max_length=255)
    emails: tuple[SCIMEmail, ...] = Field(default=(), max_length=8)
    active: bool = True

    @field_validator("schemas", "emails", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("SCIM multi-valued attributes must be JSON arrays.")
        return tuple(value)

    @model_validator(mode="after")
    def validate_resource(self) -> SCIMUserWrite:
        if self.schemas != (SCIM_USER_SCHEMA,):
            raise ValueError("schemas must contain the supported User schema exactly once.")
        external = _clean(self.externalId, "externalId", 255)
        username = _clean(self.userName, "userName", 160).casefold()
        if not _USERNAME.fullmatch(username):
            raise ValueError("userName contains unsupported characters.")
        primary_count = sum(email.primary for email in self.emails)
        if primary_count > 1:
            raise ValueError("emails may contain at most one primary value.")
        object.__setattr__(self, "externalId", external)
        object.__setattr__(self, "userName", username)
        if self.displayName is not None:
            object.__setattr__(self, "displayName", _clean(self.displayName, "displayName", 255))
        return self


class SCIMMember(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str = Field(min_length=1, max_length=64)

    @field_validator("value")
    @classmethod
    def clean_value(cls, value: str) -> str:
        return _scope(value, "member value")


class SCIMGroupWrite(BaseModel):
    """Supported, closed subset of the RFC 7643 Group write schema."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schemas: tuple[str, ...]
    externalId: str = Field(min_length=1, max_length=255)
    displayName: str = Field(min_length=1, max_length=255)
    members: tuple[SCIMMember, ...] = Field(default=(), max_length=10_000)

    @field_validator("schemas", "members", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("SCIM multi-valued attributes must be JSON arrays.")
        return tuple(value)

    @model_validator(mode="after")
    def validate_resource(self) -> SCIMGroupWrite:
        if self.schemas != (SCIM_GROUP_SCHEMA,):
            raise ValueError("schemas must contain the supported Group schema exactly once.")
        member_ids = [member.value for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("members must not contain duplicate values.")
        object.__setattr__(self, "externalId", _clean(self.externalId, "externalId", 255))
        object.__setattr__(self, "displayName", _clean(self.displayName, "displayName", 255))
        return self


@dataclass(frozen=True)
class SCIMUser:
    id: str
    provisioning_domain: str
    external_id: str
    username: str
    display_name: str
    email: str | None
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SCIMGroup:
    id: str
    provisioning_domain: str
    external_id: str
    display_name: str
    member_ids: tuple[str, ...]
    version: int
    created_at: datetime
    updated_at: datetime


class SCIMRepository(Protocol):
    def put_user(self, *, tenant_id: str, domain: str, resource: SCIMUserWrite) -> tuple[SCIMUser, bool]: ...

    def set_user_active(self, *, tenant_id: str, domain: str, resource_id: str, active: bool) -> SCIMUser: ...

    def put_group(self, *, tenant_id: str, domain: str, resource: SCIMGroupWrite) -> tuple[SCIMGroup, bool]: ...


class SCIMAuditSink(Protocol):
    def record(
        self,
        *,
        tenant_id: str,
        domain: str,
        actor_id: str,
        resource_type: Literal["User", "Group"],
        resource_id: str,
        action: str,
        outcome: Literal["ALLOWED", "DENIED"],
        reason_code: str | None,
    ) -> None: ...


@dataclass(frozen=True)
class SCIMService:
    """Tenant/domain-scoped lifecycle orchestration with sanitized audit."""

    repository: SCIMRepository
    audit: SCIMAuditSink

    def provision_user(
        self, *, tenant_id: str, provisioning_domain: str, actor_id: str, resource: SCIMUserWrite
    ) -> tuple[SCIMUser, bool]:
        tenant, domain, actor = self._context(tenant_id, provisioning_domain, actor_id)
        try:
            user, created = self.repository.put_user(tenant_id=tenant, domain=domain, resource=resource)
        except SCIMError:
            self._denied(tenant, domain, actor, "User", "unknown", "persistence_conflict")
            raise
        self.audit.record(
            tenant_id=tenant,
            domain=domain,
            actor_id=actor,
            resource_type="User",
            resource_id=user.id,
            action="CREATE" if created else "REPLACE",
            outcome="ALLOWED",
            reason_code=None,
        )
        return user, created

    def deactivate_user(self, *, tenant_id: str, provisioning_domain: str, actor_id: str, resource_id: str) -> SCIMUser:
        tenant, domain, actor = self._context(tenant_id, provisioning_domain, actor_id)
        resource = _scope(resource_id, "resource_id")
        try:
            user = self.repository.set_user_active(tenant_id=tenant, domain=domain, resource_id=resource, active=False)
        except SCIMError:
            self._denied(tenant, domain, actor, "User", resource, "resource_not_found")
            raise
        self.audit.record(
            tenant_id=tenant,
            domain=domain,
            actor_id=actor,
            resource_type="User",
            resource_id=user.id,
            action="DEACTIVATE",
            outcome="ALLOWED",
            reason_code=None,
        )
        return user

    def provision_group(
        self, *, tenant_id: str, provisioning_domain: str, actor_id: str, resource: SCIMGroupWrite
    ) -> tuple[SCIMGroup, bool]:
        tenant, domain, actor = self._context(tenant_id, provisioning_domain, actor_id)
        try:
            group, created = self.repository.put_group(tenant_id=tenant, domain=domain, resource=resource)
        except SCIMError:
            self._denied(tenant, domain, actor, "Group", "unknown", "persistence_conflict")
            raise
        self.audit.record(
            tenant_id=tenant,
            domain=domain,
            actor_id=actor,
            resource_type="Group",
            resource_id=group.id,
            action="CREATE" if created else "REPLACE",
            outcome="ALLOWED",
            reason_code=None,
        )
        return group, created

    @staticmethod
    def _context(tenant_id: str, domain: str, actor_id: str) -> tuple[str, str, str]:
        return _scope(tenant_id, "tenant_id"), _scope(domain, "provisioning_domain"), _scope(actor_id, "actor_id")

    def _denied(
        self,
        tenant: str,
        domain: str,
        actor: str,
        resource_type: Literal["User", "Group"],
        resource_id: str,
        reason: str,
    ) -> None:
        self.audit.record(
            tenant_id=tenant,
            domain=domain,
            actor_id=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            action="PROVISION",
            outcome="DENIED",
            reason_code=reason,
        )


def scim_timestamp(value: datetime) -> str:
    """Render one deterministic RFC 3339 UTC timestamp for protocol adapters."""

    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
