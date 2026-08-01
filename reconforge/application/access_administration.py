"""Backend-neutral contracts for governed role and access-policy administration."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_ROLE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_PERMISSION_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class AccessAdministrationError(ValueError):
    """Safe access-administration failure carrying one stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AccessPermissionSummary:
    name: str
    description: str
    active_role_count: int
    state_digest: str


@dataclass(frozen=True)
class AccessRoleSummary:
    id: str
    name: str
    description: str
    active: bool
    lifecycle_version: int
    permissions: tuple[str, ...]
    active_user_count: int
    created_at: str
    updated_at: str
    retired_at: str | None
    state_digest: str


@dataclass(frozen=True)
class AccessRolePage:
    items: tuple[AccessRoleSummary, ...]
    next_name: str | None = None
    next_role_id: str | None = None


@dataclass(frozen=True)
class AccessRoleChange:
    role: AccessRoleSummary
    transitioned: bool
    revoked_sessions: int
    audit_event_id: str | None


@dataclass(frozen=True)
class UserRoleAssignmentChange:
    user_id: str
    username: str
    lifecycle_version: int
    role_ids: tuple[str, ...]
    role_names: tuple[str, ...]
    transitioned: bool
    revoked_sessions: int
    audit_event_id: str | None
    state_digest: str


class AccessAdministrationRepository(Protocol):
    def list_permissions(self) -> tuple[AccessPermissionSummary, ...]: ...

    def list_roles(
        self,
        *,
        limit: int,
        include_retired: bool,
        after_name: str | None,
        after_role_id: str | None,
    ) -> AccessRolePage: ...

    def create_role(
        self,
        *,
        actor_user_id: str,
        name: str,
        description: str,
        permissions: tuple[str, ...],
        as_of: datetime,
    ) -> AccessRoleChange: ...

    def update_role(
        self,
        *,
        actor_user_id: str,
        role_id: str,
        description: str | None,
        active: bool | None,
        expected_lifecycle_version: int,
        as_of: datetime,
    ) -> AccessRoleChange: ...

    def replace_role_permissions(
        self,
        *,
        actor_user_id: str,
        role_id: str,
        permissions: tuple[str, ...],
        expected_lifecycle_version: int,
        as_of: datetime,
    ) -> AccessRoleChange: ...

    def replace_user_roles(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        role_ids: tuple[str, ...],
        expected_user_lifecycle_version: int,
        as_of: datetime,
    ) -> UserRoleAssignmentChange: ...


def _identifier(value: str, field_name: str) -> str:
    normalized = str(value).strip().casefold()
    if not _IDENTIFIER.fullmatch(normalized):
        raise AccessAdministrationError("access_identifier_invalid", f"{field_name} is invalid.")
    return normalized


def _role_name(value: str) -> str:
    normalized = str(value).strip().casefold()
    if not _ROLE_NAME.fullmatch(normalized):
        raise AccessAdministrationError("access_role_name_invalid", "Role name is invalid.")
    return normalized


def _description(value: str) -> str:
    normalized = " ".join(str(value).strip().split())
    if len(normalized) > 500 or any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise AccessAdministrationError(
            "access_role_description_invalid", "Role description must be printable and at most 500 characters."
        )
    return normalized


def _permission_names(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or len(values) > 256:
        raise AccessAdministrationError(
            "access_permission_set_invalid", "Permission set must contain at most 256 names."
        )
    normalized: list[str] = []
    for value in values:
        permission = str(value).strip().casefold()
        if not _PERMISSION_NAME.fullmatch(permission):
            raise AccessAdministrationError("access_permission_name_invalid", "Permission name is invalid.")
        normalized.append(permission)
    if len(set(normalized)) != len(normalized):
        raise AccessAdministrationError(
            "access_permission_set_invalid", "Permission names must be unique."
        )
    return tuple(sorted(normalized))


def _role_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or len(values) > 64:
        raise AccessAdministrationError("access_role_set_invalid", "Role set must contain at most 64 identifiers.")
    normalized = tuple(_identifier(value, "role_id") for value in values)
    if len(set(normalized)) != len(normalized):
        raise AccessAdministrationError("access_role_set_invalid", "Role identifiers must be unique.")
    return tuple(sorted(normalized))


def _version(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AccessAdministrationError(
            "access_lifecycle_version_invalid", f"{field_name} must be a positive integer."
        )
    return value


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200:
        raise AccessAdministrationError("access_page_limit_invalid", "limit must be between 1 and 200.")
    return value


def _utc_second(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None or value.microsecond:
        raise AccessAdministrationError(
            "access_time_invalid", "Access administration time must be timezone-aware and whole-second."
        )
    return value.astimezone(UTC)


class AccessAdministrationApplicationService:
    """Validate role and policy lifecycle requests before repository effects."""

    def __init__(self, repository: AccessAdministrationRepository, *, clock: Callable[[], datetime]) -> None:
        self.repository = repository
        self.clock = clock

    def list_permissions(self) -> tuple[AccessPermissionSummary, ...]:
        return self.repository.list_permissions()

    def list_roles(
        self,
        *,
        limit: int,
        include_retired: bool = False,
        after_name: str | None = None,
        after_role_id: str | None = None,
    ) -> AccessRolePage:
        if not isinstance(include_retired, bool):
            raise AccessAdministrationError("access_role_filter_invalid", "include_retired must be a boolean.")
        if (after_name is None) != (after_role_id is None):
            raise AccessAdministrationError(
                "access_role_cursor_invalid", "Role pagination boundary fields must be supplied together."
            )
        return self.repository.list_roles(
            limit=_limit(limit),
            include_retired=include_retired,
            after_name=None if after_name is None else _role_name(after_name),
            after_role_id=None if after_role_id is None else _identifier(after_role_id, "after_role_id"),
        )

    def create_role(
        self,
        *,
        actor_user_id: str,
        name: str,
        description: str,
        permissions: Sequence[str],
    ) -> AccessRoleChange:
        return self.repository.create_role(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            name=_role_name(name),
            description=_description(description),
            permissions=_permission_names(permissions),
            as_of=_utc_second(self.clock()),
        )

    def update_role(
        self,
        *,
        actor_user_id: str,
        role_id: str,
        expected_lifecycle_version: int,
        description: str | None = None,
        active: bool | None = None,
    ) -> AccessRoleChange:
        if description is None and active is None:
            raise AccessAdministrationError("access_role_change_empty", "At least one role change is required.")
        if active is not None and not isinstance(active, bool):
            raise AccessAdministrationError("access_role_status_invalid", "active must be a boolean.")
        return self.repository.update_role(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            role_id=_identifier(role_id, "role_id"),
            description=None if description is None else _description(description),
            active=active,
            expected_lifecycle_version=_version(expected_lifecycle_version, "expected_lifecycle_version"),
            as_of=_utc_second(self.clock()),
        )

    def replace_role_permissions(
        self,
        *,
        actor_user_id: str,
        role_id: str,
        permissions: Sequence[str],
        expected_lifecycle_version: int,
    ) -> AccessRoleChange:
        return self.repository.replace_role_permissions(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            role_id=_identifier(role_id, "role_id"),
            permissions=_permission_names(permissions),
            expected_lifecycle_version=_version(expected_lifecycle_version, "expected_lifecycle_version"),
            as_of=_utc_second(self.clock()),
        )

    def replace_user_roles(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        role_ids: Sequence[str],
        expected_user_lifecycle_version: int,
    ) -> UserRoleAssignmentChange:
        return self.repository.replace_user_roles(
            actor_user_id=_identifier(actor_user_id, "actor_user_id"),
            user_id=_identifier(user_id, "user_id"),
            role_ids=_role_ids(role_ids),
            expected_user_lifecycle_version=_version(
                expected_user_lifecycle_version, "expected_user_lifecycle_version"
            ),
            as_of=_utc_second(self.clock()),
        )
