"""Backend-neutral contracts for governed identity and session administration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

_SCOPE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_SESSION_REASONS = frozenset(
    {"access_change", "administrative_cleanup", "security_response", "user_request"}
)


class IdentityAdministrationError(ValueError):
    """Safe identity-administration failure carrying one stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class IdentityUserSummary:
    id: str
    username: str
    display_name: str
    disabled: bool
    lifecycle_version: int
    roles: tuple[str, ...]
    active_sessions: int
    created_at: str
    disabled_at: str | None
    state_digest: str


@dataclass(frozen=True)
class IdentitySessionSummary:
    id: str
    user_id: str
    username: str
    status: Literal["active", "expired", "revoked"]
    lifecycle_version: int
    created_at: str
    expires_at: str
    last_used_at: str | None
    revoked_at: str | None
    revocation_reason_code: str | None
    client_ip_recorded: bool
    user_agent_recorded: bool
    state_digest: str


@dataclass(frozen=True)
class IdentityUserPage:
    items: tuple[IdentityUserSummary, ...]
    next_username: str | None = None
    next_user_id: str | None = None


@dataclass(frozen=True)
class IdentitySessionPage:
    items: tuple[IdentitySessionSummary, ...]
    next_created_at: str | None = None
    next_session_id: str | None = None


@dataclass(frozen=True)
class UserStatusChange:
    user: IdentityUserSummary
    transitioned: bool
    revoked_sessions: int
    audit_event_id: str | None


@dataclass(frozen=True)
class SessionRevocation:
    session: IdentitySessionSummary
    transitioned: bool
    revoked_current_session: bool
    audit_event_id: str | None


class IdentityAdministrationRepository(Protocol):
    def list_users(
        self,
        *,
        as_of: datetime,
        limit: int,
        after_username: str | None,
        after_user_id: str | None,
    ) -> IdentityUserPage: ...

    def set_user_disabled(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        disabled: bool,
        expected_lifecycle_version: int,
        as_of: datetime,
    ) -> UserStatusChange: ...

    def list_sessions(
        self,
        *,
        as_of: datetime,
        user_id: str | None,
        limit: int,
        after_created_at: str | None,
        after_session_id: str | None,
    ) -> IdentitySessionPage: ...

    def revoke_session(
        self,
        *,
        actor_user_id: str,
        current_session_id: str,
        session_id: str,
        expected_lifecycle_version: int,
        reason_code: str,
        as_of: datetime,
    ) -> SessionRevocation: ...


def _scope(value: str, field_name: str) -> str:
    normalized = str(value).strip().casefold()
    if not _SCOPE.fullmatch(normalized):
        raise IdentityAdministrationError("identity_identifier_invalid", f"{field_name} is invalid.")
    return normalized


def _version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IdentityAdministrationError(
            "identity_lifecycle_version_invalid", "expected_lifecycle_version must be a positive integer."
        )
    return value


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200:
        raise IdentityAdministrationError("identity_page_limit_invalid", "limit must be between 1 and 200.")
    return value


def _utc_second(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IdentityAdministrationError("identity_time_invalid", "Identity administration time needs a timezone.")
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise IdentityAdministrationError(
            "identity_time_invalid", "Identity administration time must use whole-second precision."
        )
    return normalized


def _paired(left: str | None, right: str | None, code: str) -> tuple[str | None, str | None]:
    if (left is None) != (right is None):
        raise IdentityAdministrationError(code, "Pagination boundary fields must be supplied together.")
    return left, right


class IdentityAdministrationApplicationService:
    """Validate human-governed identity operations before repository effects."""

    def __init__(
        self,
        repository: IdentityAdministrationRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.clock = clock

    def list_users(
        self,
        *,
        limit: int,
        after_username: str | None = None,
        after_user_id: str | None = None,
    ) -> IdentityUserPage:
        after_username, after_user_id = _paired(
            after_username, after_user_id, "identity_user_cursor_invalid"
        )
        return self.repository.list_users(
            as_of=_utc_second(self.clock()),
            limit=_limit(limit),
            after_username=None if after_username is None else _scope(after_username, "after_username"),
            after_user_id=None if after_user_id is None else _scope(after_user_id, "after_user_id"),
        )

    def set_user_disabled(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        disabled: bool,
        expected_lifecycle_version: int,
    ) -> UserStatusChange:
        actor = _scope(actor_user_id, "actor_user_id")
        target = _scope(user_id, "user_id")
        if not isinstance(disabled, bool):
            raise IdentityAdministrationError("identity_status_invalid", "disabled must be a boolean.")
        if disabled and actor == target:
            raise IdentityAdministrationError(
                "identity_self_disable_forbidden", "An administrator cannot disable their own active identity."
            )
        return self.repository.set_user_disabled(
            actor_user_id=actor,
            user_id=target,
            disabled=disabled,
            expected_lifecycle_version=_version(expected_lifecycle_version),
            as_of=_utc_second(self.clock()),
        )

    def list_sessions(
        self,
        *,
        limit: int,
        user_id: str | None = None,
        after_created_at: str | None = None,
        after_session_id: str | None = None,
    ) -> IdentitySessionPage:
        after_created_at, after_session_id = _paired(
            after_created_at, after_session_id, "identity_session_cursor_invalid"
        )
        return self.repository.list_sessions(
            as_of=_utc_second(self.clock()),
            user_id=None if user_id is None else _scope(user_id, "user_id"),
            limit=_limit(limit),
            after_created_at=after_created_at,
            after_session_id=None
            if after_session_id is None
            else _scope(after_session_id, "after_session_id"),
        )

    def revoke_session(
        self,
        *,
        actor_user_id: str,
        current_session_id: str,
        session_id: str,
        expected_lifecycle_version: int,
        reason_code: str,
    ) -> SessionRevocation:
        reason = str(reason_code).strip().casefold()
        if reason not in _SESSION_REASONS:
            raise IdentityAdministrationError(
                "identity_revocation_reason_invalid", "Session revocation reason is unsupported."
            )
        return self.repository.revoke_session(
            actor_user_id=_scope(actor_user_id, "actor_user_id"),
            current_session_id=_scope(current_session_id, "current_session_id"),
            session_id=_scope(session_id, "session_id"),
            expected_lifecycle_version=_version(expected_lifecycle_version),
            reason_code=reason,
            as_of=_utc_second(self.clock()),
        )

