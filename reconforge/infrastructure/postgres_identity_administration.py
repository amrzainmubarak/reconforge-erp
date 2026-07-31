"""PostgreSQL adapter for governed identity and session administration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from reconforge.application.identity_administration import (
    IdentityAdministrationError,
    IdentitySessionPage,
    IdentitySessionSummary,
    IdentityUserPage,
    IdentityUserSummary,
    SessionRevocation,
    UserStatusChange,
)
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository

_SESSION_REASONS = frozenset(
    {"access_change", "administrative_cleanup", "security_response", "user_request"}
)


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise IdentityAdministrationError("identity_identifier_invalid", f"{field_name} is invalid.") from exc


def _utc_text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise IdentityAdministrationError(
                "identity_persisted_time_invalid", "Stored identity time is invalid."
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IdentityAdministrationError("identity_persisted_time_invalid", "Stored identity time needs a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _actor_digest(value: object | None) -> str | None:
    return None if value is None else hashlib.sha256(str(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PostgresIdentityAdministrationRepository:
    """Perform bounded identity lifecycle effects in the caller transaction."""

    connection: Any
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _scope(self.tenant_id, "tenant_id"))

    @staticmethod
    def _validate_clock(as_of: datetime) -> datetime:
        if as_of.tzinfo is None or as_of.utcoffset() is None or as_of.microsecond:
            raise IdentityAdministrationError(
                "identity_time_invalid", "Identity administration time must be timezone-aware and whole-second."
            )
        return as_of.astimezone(UTC)

    def _lock(self) -> None:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"identity-administration:{self.tenant_id}",),
        )

    @staticmethod
    def _user(row: Any) -> IdentityUserSummary:
        roles_value = _value(row, "roles", 7)
        roles = tuple(sorted(str(item) for item in (roles_value or ())))
        created_at = _utc_text(_value(row, "created_at", 5))
        disabled_at = _utc_text(_value(row, "disabled_at", 6))
        lifecycle_version = int(_value(row, "lifecycle_version", 4))
        active_sessions = int(_value(row, "active_sessions", 8))
        disabled_by_digest = _actor_digest(_value(row, "disabled_by", 9))
        state = {
            "active_sessions": active_sessions,
            "created_at": created_at,
            "disabled": bool(_value(row, "disabled", 3)),
            "disabled_at": disabled_at,
            "disabled_by_digest": disabled_by_digest,
            "display_name": str(_value(row, "display_name", 2)),
            "id": str(_value(row, "id", 0)),
            "lifecycle_version": lifecycle_version,
            "roles": list(roles),
            "username": str(_value(row, "username", 1)),
        }
        return IdentityUserSummary(
            id=str(state["id"]),
            username=str(state["username"]),
            display_name=str(state["display_name"]),
            disabled=bool(state["disabled"]),
            lifecycle_version=lifecycle_version,
            roles=roles,
            active_sessions=active_sessions,
            created_at=str(created_at),
            disabled_at=disabled_at,
            state_digest=_digest(state),
        )

    @staticmethod
    def _session(row: Any, as_of: datetime) -> IdentitySessionSummary:
        created_at = _utc_text(_value(row, "created_at", 3))
        expires_at = _utc_text(_value(row, "expires_at", 4))
        last_used_at = _utc_text(_value(row, "last_used_at", 5))
        revoked_at = _utc_text(_value(row, "revoked_at", 6))
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        status: Literal["active", "expired", "revoked"] = (
            "revoked" if revoked_at is not None else ("expired" if expires <= as_of else "active")
        )
        lifecycle_version = int(_value(row, "lifecycle_version", 7))
        reason = None if _value(row, "revocation_reason_code", 8) is None else str(
            _value(row, "revocation_reason_code", 8)
        )
        state = {
            "client_ip_recorded": bool(_value(row, "client_ip_recorded", 9)),
            "created_at": created_at,
            "expires_at": expires_at,
            "id": str(_value(row, "id", 0)),
            "last_used_at": last_used_at,
            "lifecycle_version": lifecycle_version,
            "revocation_reason_code": reason,
            "revoked_at": revoked_at,
            "revoked_by_digest": _actor_digest(_value(row, "revoked_by", 11)),
            "status": status,
            "user_agent_recorded": bool(_value(row, "user_agent_recorded", 10)),
            "user_id": str(_value(row, "user_id", 1)),
            "username": str(_value(row, "username", 2)),
        }
        return IdentitySessionSummary(
            id=str(state["id"]),
            user_id=str(state["user_id"]),
            username=str(state["username"]),
            status=status,
            lifecycle_version=lifecycle_version,
            created_at=str(created_at),
            expires_at=str(expires_at),
            last_used_at=last_used_at,
            revoked_at=revoked_at,
            revocation_reason_code=reason,
            client_ip_recorded=bool(state["client_ip_recorded"]),
            user_agent_recorded=bool(state["user_agent_recorded"]),
            state_digest=_digest(state),
        )

    def _user_row(self, *, user_id: str, as_of: datetime, for_update: bool = False) -> Any | None:
        query = (
            """
            SELECT u.id,u.username,u.display_name,u.disabled,u.lifecycle_version,u.created_at,u.disabled_at,
                   ARRAY(SELECT r.name FROM reconforge.identity_user_roles ur
                         JOIN reconforge.identity_roles r
                           ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                         WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id
                           AND ur.active AND r.active ORDER BY r.name) AS roles,
                   (SELECT count(*) FROM reconforge.identity_sessions s
                     WHERE s.tenant_id=u.tenant_id AND s.user_id=u.id
                       AND s.revoked_at IS NULL AND s.expires_at>%s) AS active_sessions,
                   u.disabled_by
              FROM reconforge.identity_users u
             WHERE u.tenant_id=%s AND u.id=%s
             FOR UPDATE OF u
            """
            if for_update
            else """
            SELECT u.id,u.username,u.display_name,u.disabled,u.lifecycle_version,u.created_at,u.disabled_at,
                   ARRAY(SELECT r.name FROM reconforge.identity_user_roles ur
                         JOIN reconforge.identity_roles r
                           ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                         WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id
                           AND ur.active AND r.active ORDER BY r.name) AS roles,
                   (SELECT count(*) FROM reconforge.identity_sessions s
                     WHERE s.tenant_id=u.tenant_id AND s.user_id=u.id
                       AND s.revoked_at IS NULL AND s.expires_at>%s) AS active_sessions,
                   u.disabled_by
              FROM reconforge.identity_users u
             WHERE u.tenant_id=%s AND u.id=%s
            """
        )
        return self.connection.execute(
            query,
            (as_of, self.tenant_id, user_id),
        ).fetchone()

    def list_users(
        self,
        *,
        as_of: datetime,
        limit: int,
        after_username: str | None,
        after_user_id: str | None,
    ) -> IdentityUserPage:
        instant = self._validate_clock(as_of)
        if after_username is None:
            cursor = self.connection.execute(
                """
                SELECT u.id,u.username,u.display_name,u.disabled,u.lifecycle_version,u.created_at,u.disabled_at,
                       ARRAY(SELECT r.name FROM reconforge.identity_user_roles ur
                             JOIN reconforge.identity_roles r
                               ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                             WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id
                               AND ur.active AND r.active ORDER BY r.name),
                       (SELECT count(*) FROM reconforge.identity_sessions s
                         WHERE s.tenant_id=u.tenant_id AND s.user_id=u.id
                           AND s.revoked_at IS NULL AND s.expires_at>%s),
                       u.disabled_by
                  FROM reconforge.identity_users u
                 WHERE u.tenant_id=%s
                 ORDER BY u.username,u.id LIMIT %s
                """,
                (instant, self.tenant_id, limit + 1),
            )
        else:
            cursor = self.connection.execute(
                """
                SELECT u.id,u.username,u.display_name,u.disabled,u.lifecycle_version,u.created_at,u.disabled_at,
                       ARRAY(SELECT r.name FROM reconforge.identity_user_roles ur
                             JOIN reconforge.identity_roles r
                               ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                             WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id
                               AND ur.active AND r.active ORDER BY r.name),
                       (SELECT count(*) FROM reconforge.identity_sessions s
                         WHERE s.tenant_id=u.tenant_id AND s.user_id=u.id
                           AND s.revoked_at IS NULL AND s.expires_at>%s),
                       u.disabled_by
                  FROM reconforge.identity_users u
                 WHERE u.tenant_id=%s AND (u.username,u.id)>(%s,%s)
                 ORDER BY u.username,u.id LIMIT %s
                """,
                (instant, self.tenant_id, after_username, after_user_id, limit + 1),
            )
        rows = cursor.fetchall()
        selected = rows[:limit]
        items = tuple(self._user(row) for row in selected)
        if len(rows) <= limit or not items:
            return IdentityUserPage(items)
        last = items[-1]
        return IdentityUserPage(items, next_username=last.username, next_user_id=last.id)

    def set_user_disabled(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        disabled: bool,
        expected_lifecycle_version: int,
        as_of: datetime,
    ) -> UserStatusChange:
        instant = self._validate_clock(as_of)
        actor = _scope(actor_user_id, "actor_user_id")
        target = _scope(user_id, "user_id")
        if disabled and actor == target:
            raise IdentityAdministrationError(
                "identity_self_disable_forbidden", "An administrator cannot disable their own active identity."
            )
        self._lock()
        actor_row = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled",
            (self.tenant_id, actor),
        ).fetchone()
        if actor_row is None:
            raise IdentityAdministrationError("identity_actor_inactive", "The administrative actor is unavailable.")
        current_row = self._user_row(user_id=target, as_of=instant, for_update=True)
        if current_row is None:
            raise IdentityAdministrationError("identity_user_not_found", "Identity user was not found.")
        current = self._user(current_row)
        if current.lifecycle_version != expected_lifecycle_version:
            raise IdentityAdministrationError(
                "identity_lifecycle_version_conflict", "Identity lifecycle version does not match."
            )
        if current.disabled == disabled:
            return UserStatusChange(current, False, 0, None)
        if disabled:
            target_admin_permissions = self.connection.execute(
                """SELECT DISTINCT rp.permission_name FROM reconforge.identity_user_roles ur
                   JOIN reconforge.identity_roles r
                     ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                   JOIN reconforge.identity_role_permissions rp
                     ON rp.tenant_id=ur.tenant_id AND rp.role_id=ur.role_id
                   WHERE ur.tenant_id=%s AND ur.user_id=%s AND ur.active AND r.active AND rp.active
                     AND rp.permission_name IN ('users.manage','roles.manage')
                   ORDER BY rp.permission_name""",
                (self.tenant_id, target),
            ).fetchall()
            for permission_row in target_admin_permissions:
                permission_name = str(_value(permission_row, "permission_name", 0))
                active_admin_row = self.connection.execute(
                    """SELECT count(DISTINCT u.id) AS active_admins FROM reconforge.identity_users u
                           JOIN reconforge.identity_user_roles ur
                             ON ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active
                           JOIN reconforge.identity_roles r
                             ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id AND r.active
                           JOIN reconforge.identity_role_permissions rp
                             ON rp.tenant_id=ur.tenant_id AND rp.role_id=ur.role_id AND rp.active
                           WHERE u.tenant_id=%s AND NOT u.disabled AND rp.permission_name=%s""",
                    (self.tenant_id, permission_name),
                ).fetchone()
                active_admins = 0 if active_admin_row is None else int(
                    _value(active_admin_row, "active_admins", 0)
                )
                if active_admins <= 1:
                    raise IdentityAdministrationError(
                        "identity_last_administrator_forbidden",
                        "The last active identity or access administrator cannot be disabled.",
                    )
        updated = self.connection.execute(
            """UPDATE reconforge.identity_users
               SET disabled=%s, disabled_at=%s, disabled_by=%s,
                   lifecycle_version=lifecycle_version+1, updated_at=%s
               WHERE tenant_id=%s AND id=%s AND lifecycle_version=%s
               RETURNING id""",
            (
                disabled,
                instant if disabled else None,
                actor if disabled else None,
                instant,
                self.tenant_id,
                target,
                expected_lifecycle_version,
            ),
        ).fetchone()
        if updated is None:
            raise IdentityAdministrationError(
                "identity_lifecycle_version_conflict", "Identity lifecycle version does not match."
            )
        revoked_sessions = 0
        if disabled:
            revoked_sessions = len(
                self.connection.execute(
                    """UPDATE reconforge.identity_sessions
                       SET revoked_at=%s, revocation_reason_code='user_disabled', revoked_by=%s,
                           lifecycle_version=lifecycle_version+1
                       WHERE tenant_id=%s AND user_id=%s AND revoked_at IS NULL
                       RETURNING id""",
                    (instant, actor, self.tenant_id, target),
                ).fetchall()
            )
        after_row = self._user_row(user_id=target, as_of=instant)
        if after_row is None:
            raise IdentityAdministrationError("identity_user_not_found", "Identity user was not found.")
        after = self._user(after_row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="identity_user",
            object_id=target,
            action="identity.user.disabled" if disabled else "identity.user.enabled",
            before_hash=current.state_digest,
            after_hash=after.state_digest,
            metadata={
                "lifecycle_version": after.lifecycle_version,
                "revoked_session_count": revoked_sessions,
                "schema_version": 1,
            },
        )
        return UserStatusChange(after, True, revoked_sessions, audit.id)

    def _session_row(self, *, session_id: str, for_update: bool = False) -> Any | None:
        query = (
            """SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.last_used_at,s.revoked_at,
                      s.lifecycle_version,s.revocation_reason_code,(s.client_ip IS NOT NULL),
                      (s.user_agent IS NOT NULL),s.revoked_by
                 FROM reconforge.identity_sessions s
                 JOIN reconforge.identity_users u ON u.tenant_id=s.tenant_id AND u.id=s.user_id
                WHERE s.tenant_id=%s AND s.id=%s
                FOR UPDATE OF s"""
            if for_update
            else """SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.last_used_at,s.revoked_at,
                      s.lifecycle_version,s.revocation_reason_code,(s.client_ip IS NOT NULL),
                      (s.user_agent IS NOT NULL),s.revoked_by
                 FROM reconforge.identity_sessions s
                 JOIN reconforge.identity_users u ON u.tenant_id=s.tenant_id AND u.id=s.user_id
                WHERE s.tenant_id=%s AND s.id=%s"""
        )
        return self.connection.execute(
            query,
            (self.tenant_id, session_id),
        ).fetchone()

    def list_sessions(
        self,
        *,
        as_of: datetime,
        user_id: str | None,
        limit: int,
        after_created_at: str | None,
        after_session_id: str | None,
    ) -> IdentitySessionPage:
        instant = self._validate_clock(as_of)
        target_user = None if user_id is None else _scope(user_id, "user_id")
        boundary = None
        if after_created_at is not None:
            parsed = _utc_text(after_created_at)
            boundary = datetime.fromisoformat(str(parsed).replace("Z", "+00:00"))
        parameters: tuple[object, ...]
        if target_user is None and boundary is None:
            sql = """SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.last_used_at,s.revoked_at,
                            s.lifecycle_version,s.revocation_reason_code,(s.client_ip IS NOT NULL),
                            (s.user_agent IS NOT NULL),s.revoked_by
                       FROM reconforge.identity_sessions s
                       JOIN reconforge.identity_users u ON u.tenant_id=s.tenant_id AND u.id=s.user_id
                      WHERE s.tenant_id=%s ORDER BY s.created_at DESC,s.id DESC LIMIT %s"""
            parameters = (self.tenant_id, limit + 1)
        elif target_user is not None and boundary is None:
            sql = """SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.last_used_at,s.revoked_at,
                            s.lifecycle_version,s.revocation_reason_code,(s.client_ip IS NOT NULL),
                            (s.user_agent IS NOT NULL),s.revoked_by
                       FROM reconforge.identity_sessions s
                       JOIN reconforge.identity_users u ON u.tenant_id=s.tenant_id AND u.id=s.user_id
                      WHERE s.tenant_id=%s AND s.user_id=%s
                      ORDER BY s.created_at DESC,s.id DESC LIMIT %s"""
            parameters = (self.tenant_id, target_user, limit + 1)
        elif target_user is None:
            sql = """SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.last_used_at,s.revoked_at,
                            s.lifecycle_version,s.revocation_reason_code,(s.client_ip IS NOT NULL),
                            (s.user_agent IS NOT NULL),s.revoked_by
                       FROM reconforge.identity_sessions s
                       JOIN reconforge.identity_users u ON u.tenant_id=s.tenant_id AND u.id=s.user_id
                      WHERE s.tenant_id=%s AND (s.created_at,s.id)<(%s,%s)
                      ORDER BY s.created_at DESC,s.id DESC LIMIT %s"""
            parameters = (self.tenant_id, boundary, after_session_id, limit + 1)
        else:
            sql = """SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.last_used_at,s.revoked_at,
                            s.lifecycle_version,s.revocation_reason_code,(s.client_ip IS NOT NULL),
                            (s.user_agent IS NOT NULL),s.revoked_by
                       FROM reconforge.identity_sessions s
                       JOIN reconforge.identity_users u ON u.tenant_id=s.tenant_id AND u.id=s.user_id
                      WHERE s.tenant_id=%s AND s.user_id=%s AND (s.created_at,s.id)<(%s,%s)
                      ORDER BY s.created_at DESC,s.id DESC LIMIT %s"""
            parameters = (self.tenant_id, target_user, boundary, after_session_id, limit + 1)
        rows = self.connection.execute(sql, parameters).fetchall()
        items = tuple(self._session(row, instant) for row in rows[:limit])
        if len(rows) <= limit or not items:
            return IdentitySessionPage(items)
        last = items[-1]
        return IdentitySessionPage(items, next_created_at=last.created_at, next_session_id=last.id)

    def revoke_session(
        self,
        *,
        actor_user_id: str,
        current_session_id: str,
        session_id: str,
        expected_lifecycle_version: int,
        reason_code: str,
        as_of: datetime,
    ) -> SessionRevocation:
        instant = self._validate_clock(as_of)
        actor = _scope(actor_user_id, "actor_user_id")
        current_session = _scope(current_session_id, "current_session_id")
        target = _scope(session_id, "session_id")
        normalized_reason = str(reason_code).strip().casefold()
        if normalized_reason not in _SESSION_REASONS:
            raise IdentityAdministrationError(
                "identity_revocation_reason_invalid", "Session revocation reason is unsupported."
            )
        self._lock()
        actor_row = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled",
            (self.tenant_id, actor),
        ).fetchone()
        if actor_row is None:
            raise IdentityAdministrationError("identity_actor_inactive", "The administrative actor is unavailable.")
        current_row = self._session_row(session_id=target, for_update=True)
        if current_row is None:
            raise IdentityAdministrationError("identity_session_not_found", "Identity session was not found.")
        current = self._session(current_row, instant)
        if current.lifecycle_version != expected_lifecycle_version:
            raise IdentityAdministrationError(
                "identity_lifecycle_version_conflict", "Identity lifecycle version does not match."
            )
        if current.revoked_at is not None:
            return SessionRevocation(current, False, target == current_session, None)
        updated = self.connection.execute(
            """UPDATE reconforge.identity_sessions
               SET revoked_at=%s, revocation_reason_code=%s, revoked_by=%s,
                   lifecycle_version=lifecycle_version+1
               WHERE tenant_id=%s AND id=%s AND lifecycle_version=%s AND revoked_at IS NULL
               RETURNING id""",
            (instant, normalized_reason, actor, self.tenant_id, target, expected_lifecycle_version),
        ).fetchone()
        if updated is None:
            raise IdentityAdministrationError(
                "identity_lifecycle_version_conflict", "Identity lifecycle version does not match."
            )
        after_row = self._session_row(session_id=target)
        if after_row is None:
            raise IdentityAdministrationError("identity_session_not_found", "Identity session was not found.")
        after = self._session(after_row, instant)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="identity_session",
            object_id=target,
            action="identity.session.revoked",
            before_hash=current.state_digest,
            after_hash=after.state_digest,
            metadata={"reason_code": normalized_reason, "schema_version": 1},
        )
        return SessionRevocation(after, True, target == current_session, audit.id)
