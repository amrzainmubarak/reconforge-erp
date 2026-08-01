"""PostgreSQL adapter for governed role and access-policy administration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from reconforge.application.access_administration import (
    AccessAdministrationError,
    AccessPermissionSummary,
    AccessRoleChange,
    AccessRolePage,
    AccessRoleSummary,
    UserRoleAssignmentChange,
)
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise AccessAdministrationError("access_identifier_invalid", f"{field_name} is invalid.") from exc


def _utc_text(value: object | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccessAdministrationError(
            "access_persisted_time_invalid", "Stored access time is invalid."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AccessAdministrationError("access_persisted_time_invalid", "Stored access time needs a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _actor_digest(value: object | None) -> str | None:
    return None if value is None else hashlib.sha256(str(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PostgresAccessAdministrationRepository:
    """Perform tenant-bound RBAC lifecycle effects in the caller transaction."""

    connection: Any
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _scope(self.tenant_id, "tenant_id"))

    @staticmethod
    def _validate_clock(as_of: datetime) -> datetime:
        if as_of.tzinfo is None or as_of.utcoffset() is None or as_of.microsecond:
            raise AccessAdministrationError(
                "access_time_invalid", "Access administration time must be timezone-aware and whole-second."
            )
        return as_of.astimezone(UTC)

    def _lock(self) -> None:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"access-administration:{self.tenant_id}",),
        )

    def _require_actor(self, actor_user_id: str) -> str:
        actor = _scope(actor_user_id, "actor_user_id")
        row = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled",
            (self.tenant_id, actor),
        ).fetchone()
        if row is None:
            raise AccessAdministrationError("access_actor_inactive", "The administrative actor is unavailable.")
        return actor

    @staticmethod
    def _role(row: Any) -> AccessRoleSummary:
        permissions = tuple(sorted(str(item) for item in (_value(row, "permissions", 8) or ())))
        created_at = _utc_text(_value(row, "created_at", 5))
        updated_at = _utc_text(_value(row, "updated_at", 6))
        retired_at = _utc_text(_value(row, "retired_at", 7))
        lifecycle_version = int(_value(row, "lifecycle_version", 4))
        active_user_count = int(_value(row, "active_user_count", 9))
        state = {
            "active": bool(_value(row, "active", 3)),
            "active_user_count": active_user_count,
            "created_at": created_at,
            "created_by_digest": _actor_digest(_value(row, "created_by", 11)),
            "description": str(_value(row, "description", 2)),
            "id": str(_value(row, "id", 0)),
            "lifecycle_version": lifecycle_version,
            "name": str(_value(row, "name", 1)),
            "permissions": list(permissions),
            "retired_at": retired_at,
            "retired_by_digest": _actor_digest(_value(row, "retired_by", 10)),
            "updated_at": updated_at,
        }
        return AccessRoleSummary(
            id=str(state["id"]),
            name=str(state["name"]),
            description=str(state["description"]),
            active=bool(state["active"]),
            lifecycle_version=lifecycle_version,
            permissions=permissions,
            active_user_count=active_user_count,
            created_at=str(created_at),
            updated_at=str(updated_at),
            retired_at=retired_at,
            state_digest=_digest(state),
        )

    def _role_row(self, role_id: str, *, for_update: bool = False) -> Any | None:
        query = (
            """SELECT r.id,r.name,r.description,r.active,r.lifecycle_version,r.created_at,r.updated_at,
                      r.retired_at,
                      ARRAY(SELECT rp.permission_name FROM reconforge.identity_role_permissions rp
                             WHERE rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                             ORDER BY rp.permission_name) AS permissions,
                      (SELECT count(*) FROM reconforge.identity_user_roles ur
                        JOIN reconforge.identity_users u
                          ON u.tenant_id=ur.tenant_id AND u.id=ur.user_id
                       WHERE ur.tenant_id=r.tenant_id AND ur.role_id=r.id AND ur.active AND NOT u.disabled),
                      r.retired_by,r.created_by
                 FROM reconforge.identity_roles r
                WHERE r.tenant_id=%s AND r.id=%s
                FOR UPDATE OF r"""
            if for_update
            else """SELECT r.id,r.name,r.description,r.active,r.lifecycle_version,r.created_at,r.updated_at,
                      r.retired_at,
                      ARRAY(SELECT rp.permission_name FROM reconforge.identity_role_permissions rp
                             WHERE rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                             ORDER BY rp.permission_name) AS permissions,
                      (SELECT count(*) FROM reconforge.identity_user_roles ur
                        JOIN reconforge.identity_users u
                          ON u.tenant_id=ur.tenant_id AND u.id=ur.user_id
                       WHERE ur.tenant_id=r.tenant_id AND ur.role_id=r.id AND ur.active AND NOT u.disabled),
                      r.retired_by,r.created_by
                 FROM reconforge.identity_roles r
                WHERE r.tenant_id=%s AND r.id=%s"""
        )
        return self.connection.execute(query, (self.tenant_id, role_id)).fetchone()

    def list_permissions(self) -> tuple[AccessPermissionSummary, ...]:
        rows = self.connection.execute(
            """SELECT p.name,p.description,
                      (SELECT count(*) FROM reconforge.identity_role_permissions rp
                        JOIN reconforge.identity_roles r
                          ON r.tenant_id=rp.tenant_id AND r.id=rp.role_id
                       WHERE rp.tenant_id=p.tenant_id AND rp.permission_name=p.name
                         AND rp.active AND r.active) AS active_role_count
                 FROM reconforge.identity_permissions p
                WHERE p.tenant_id=%s ORDER BY p.name LIMIT 513""",
            (self.tenant_id,),
        ).fetchall()
        if len(rows) > 512:
            raise AccessAdministrationError(
                "access_permission_registry_too_large", "Permission registry exceeds the supported bound."
            )
        result: list[AccessPermissionSummary] = []
        for row in rows:
            state = {
                "active_role_count": int(_value(row, "active_role_count", 2)),
                "description": str(_value(row, "description", 1)),
                "name": str(_value(row, "name", 0)),
            }
            result.append(
                AccessPermissionSummary(
                    name=str(state["name"]),
                    description=str(state["description"]),
                    active_role_count=int(_value(row, "active_role_count", 2)),
                    state_digest=_digest(state),
                )
            )
        return tuple(result)

    def list_roles(
        self,
        *,
        limit: int,
        include_retired: bool,
        after_name: str | None,
        after_role_id: str | None,
    ) -> AccessRolePage:
        if after_name is None:
            rows = self.connection.execute(
                """SELECT r.id,r.name,r.description,r.active,r.lifecycle_version,r.created_at,r.updated_at,
                          r.retired_at,
                          ARRAY(SELECT rp.permission_name FROM reconforge.identity_role_permissions rp
                                 WHERE rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                                 ORDER BY rp.permission_name),
                          (SELECT count(*) FROM reconforge.identity_user_roles ur
                            JOIN reconforge.identity_users u
                              ON u.tenant_id=ur.tenant_id AND u.id=ur.user_id
                           WHERE ur.tenant_id=r.tenant_id AND ur.role_id=r.id AND ur.active AND NOT u.disabled),
                          r.retired_by,r.created_by
                     FROM reconforge.identity_roles r
                    WHERE r.tenant_id=%s AND (%s OR r.active)
                    ORDER BY r.name,r.id LIMIT %s""",
                (self.tenant_id, include_retired, limit + 1),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT r.id,r.name,r.description,r.active,r.lifecycle_version,r.created_at,r.updated_at,
                          r.retired_at,
                          ARRAY(SELECT rp.permission_name FROM reconforge.identity_role_permissions rp
                                 WHERE rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                                 ORDER BY rp.permission_name),
                          (SELECT count(*) FROM reconforge.identity_user_roles ur
                            JOIN reconforge.identity_users u
                              ON u.tenant_id=ur.tenant_id AND u.id=ur.user_id
                           WHERE ur.tenant_id=r.tenant_id AND ur.role_id=r.id AND ur.active AND NOT u.disabled),
                          r.retired_by,r.created_by
                     FROM reconforge.identity_roles r
                    WHERE r.tenant_id=%s AND (%s OR r.active) AND (r.name,r.id)>(%s,%s)
                    ORDER BY r.name,r.id LIMIT %s""",
                (self.tenant_id, include_retired, after_name, after_role_id, limit + 1),
            ).fetchall()
        items = tuple(self._role(row) for row in rows[:limit])
        if len(rows) <= limit or not items:
            return AccessRolePage(items)
        last = items[-1]
        return AccessRolePage(items, next_name=last.name, next_role_id=last.id)

    def _validate_permissions(self, permissions: Sequence[str]) -> None:
        if not permissions:
            return
        rows = self.connection.execute(
            """SELECT name FROM reconforge.identity_permissions
               WHERE tenant_id=%s AND name=ANY(%s) ORDER BY name""",
            (self.tenant_id, list(permissions)),
        ).fetchall()
        found = tuple(str(_value(row, "name", 0)) for row in rows)
        if found != tuple(sorted(permissions)):
            raise AccessAdministrationError(
                "access_permission_not_found", "One or more permissions are not registered for this tenant."
            )

    def _validate_active_roles(self, role_ids: Sequence[str]) -> tuple[tuple[str, str], ...]:
        if not role_ids:
            return ()
        rows = self.connection.execute(
            """SELECT id,name FROM reconforge.identity_roles
               WHERE tenant_id=%s AND id=ANY(%s) AND active ORDER BY id""",
            (self.tenant_id, list(role_ids)),
        ).fetchall()
        found = tuple((str(_value(row, "id", 0)), str(_value(row, "name", 1))) for row in rows)
        if tuple(item[0] for item in found) != tuple(sorted(role_ids)):
            raise AccessAdministrationError(
                "access_role_not_found", "One or more active roles were not found for this tenant."
            )
        return found

    def _role_grants_management(self, role_id: str) -> bool:
        return self.connection.execute(
            """SELECT 1 FROM reconforge.identity_role_permissions
               WHERE tenant_id=%s AND role_id=%s AND permission_name='roles.manage' AND active""",
            (self.tenant_id, role_id),
        ).fetchone() is not None

    def _active_manager_count_excluding_role(self, role_id: str) -> int:
        row = self.connection.execute(
            """SELECT count(DISTINCT u.id)
                 FROM reconforge.identity_users u
                 JOIN reconforge.identity_user_roles ur
                   ON ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active
                 JOIN reconforge.identity_roles r
                   ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id AND r.active
                 JOIN reconforge.identity_role_permissions rp
                   ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                WHERE u.tenant_id=%s AND NOT u.disabled AND rp.permission_name='roles.manage'
                  AND r.id<>%s""",
            (self.tenant_id, role_id),
        ).fetchone()
        return int(_value(row, "count", 0)) if row is not None else 0

    def _active_manager_count_excluding_user(self, user_id: str) -> int:
        row = self.connection.execute(
            """SELECT count(DISTINCT u.id)
                 FROM reconforge.identity_users u
                 JOIN reconforge.identity_user_roles ur
                   ON ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active
                 JOIN reconforge.identity_roles r
                   ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id AND r.active
                 JOIN reconforge.identity_role_permissions rp
                   ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                WHERE u.tenant_id=%s AND u.id<>%s AND NOT u.disabled
                  AND rp.permission_name='roles.manage'""",
            (self.tenant_id, user_id),
        ).fetchone()
        return int(_value(row, "count", 0)) if row is not None else 0

    def _roles_grant_management(self, role_ids: Sequence[str]) -> bool:
        if not role_ids:
            return False
        return self.connection.execute(
            """SELECT 1 FROM reconforge.identity_roles r
                 JOIN reconforge.identity_role_permissions rp
                   ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                WHERE r.tenant_id=%s AND r.id=ANY(%s) AND r.active
                  AND rp.permission_name='roles.manage' LIMIT 1""",
            (self.tenant_id, list(role_ids)),
        ).fetchone() is not None

    def _revoke_sessions(self, user_ids: Sequence[str], actor: str, instant: datetime) -> int:
        if not user_ids:
            return 0
        rows = self.connection.execute(
            """UPDATE reconforge.identity_sessions
                  SET revoked_at=%s,revocation_reason_code='access_change',revoked_by=%s,
                      lifecycle_version=lifecycle_version+1
                WHERE tenant_id=%s AND user_id=ANY(%s) AND revoked_at IS NULL AND expires_at>%s
                RETURNING id""",
            (instant, actor, self.tenant_id, list(user_ids), instant),
        ).fetchall()
        return len(rows)

    def _increment_users(self, user_ids: Sequence[str]) -> None:
        if user_ids:
            self.connection.execute(
                """UPDATE reconforge.identity_users
                      SET lifecycle_version=lifecycle_version+1,updated_at=now()
                    WHERE tenant_id=%s AND id=ANY(%s)""",
                (self.tenant_id, list(user_ids)),
            )

    def create_role(
        self,
        *,
        actor_user_id: str,
        name: str,
        description: str,
        permissions: tuple[str, ...],
        as_of: datetime,
    ) -> AccessRoleChange:
        instant = self._validate_clock(as_of)
        self._lock()
        actor = self._require_actor(actor_user_id)
        self._validate_permissions(permissions)
        if self.connection.execute(
            "SELECT 1 FROM reconforge.identity_roles WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, name),
        ).fetchone() is not None:
            raise AccessAdministrationError("access_role_exists", "A role with this name already exists.")
        role_id = f"role-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:32]}"
        self.connection.execute(
            """INSERT INTO reconforge.identity_roles
                   (tenant_id,id,name,description,active,lifecycle_version,created_by,created_at,updated_at)
               VALUES (%s,%s,%s,%s,TRUE,1,%s,%s,%s)""",
            (self.tenant_id, role_id, name, description, actor, instant, instant),
        )
        for permission in permissions:
            self.connection.execute(
                """INSERT INTO reconforge.identity_role_permissions
                       (tenant_id,role_id,permission_name,active,lifecycle_version,granted_at,granted_by)
                   VALUES (%s,%s,%s,TRUE,1,%s,%s)""",
                (self.tenant_id, role_id, permission, instant, actor),
            )
        row = self._role_row(role_id)
        if row is None:
            raise AccessAdministrationError("access_role_not_found", "Role was not returned after creation.")
        role = self._role(row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="identity_role",
            object_id=role_id,
            action="access.role.created",
            before_hash=None,
            after_hash=role.state_digest,
            metadata={"permission_count": len(permissions), "schema_version": 1},
        )
        return AccessRoleChange(role, True, 0, audit.id)

    def update_role(
        self,
        *,
        actor_user_id: str,
        role_id: str,
        description: str | None,
        active: bool | None,
        expected_lifecycle_version: int,
        as_of: datetime,
    ) -> AccessRoleChange:
        instant = self._validate_clock(as_of)
        target = _scope(role_id, "role_id")
        self._lock()
        actor = self._require_actor(actor_user_id)
        row = self._role_row(target, for_update=True)
        if row is None:
            raise AccessAdministrationError("access_role_not_found", "Role was not found.")
        current = self._role(row)
        if current.lifecycle_version != expected_lifecycle_version:
            raise AccessAdministrationError(
                "access_lifecycle_version_conflict", "Role lifecycle version does not match."
            )
        next_description = current.description if description is None else description
        next_active = current.active if active is None else active
        if next_description == current.description and next_active == current.active:
            return AccessRoleChange(current, False, 0, None)
        affected_users: tuple[str, ...] = ()
        if current.active and not next_active:
            if self._role_grants_management(target) and self._active_manager_count_excluding_role(target) < 1:
                raise AccessAdministrationError(
                    "access_last_manager_forbidden", "The last active roles.manage authority cannot be removed."
                )
            affected_rows = self.connection.execute(
                """SELECT user_id FROM reconforge.identity_user_roles
                   WHERE tenant_id=%s AND role_id=%s AND active ORDER BY user_id FOR UPDATE""",
                (self.tenant_id, target),
            ).fetchall()
            affected_users = tuple(str(_value(item, "user_id", 0)) for item in affected_rows)
            self.connection.execute(
                """UPDATE reconforge.identity_user_roles
                      SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=%s,
                          revoked_by=%s,revocation_reason_code='role_retired'
                    WHERE tenant_id=%s AND role_id=%s AND active""",
                (instant, actor, self.tenant_id, target),
            )
        updated = self.connection.execute(
            """UPDATE reconforge.identity_roles
                  SET description=%s,active=%s,lifecycle_version=lifecycle_version+1,
                      retired_at=CASE WHEN %s THEN NULL ELSE %s END,
                      retired_by=CASE WHEN %s THEN NULL ELSE %s END,updated_at=%s
                WHERE tenant_id=%s AND id=%s AND lifecycle_version=%s
                RETURNING id""",
            (
                next_description,
                next_active,
                next_active,
                instant,
                next_active,
                actor,
                instant,
                self.tenant_id,
                target,
                expected_lifecycle_version,
            ),
        ).fetchone()
        if updated is None:
            raise AccessAdministrationError(
                "access_lifecycle_version_conflict", "Role lifecycle version does not match."
            )
        self._increment_users(affected_users)
        revoked_sessions = self._revoke_sessions(affected_users, actor, instant)
        after_row = self._role_row(target)
        if after_row is None:
            raise AccessAdministrationError("access_role_not_found", "Role was not found.")
        after = self._role(after_row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="identity_role",
            object_id=target,
            action="access.role.updated",
            before_hash=current.state_digest,
            after_hash=after.state_digest,
            metadata={
                "affected_user_count": len(affected_users),
                "retired": current.active and not after.active,
                "revoked_session_count": revoked_sessions,
                "schema_version": 1,
            },
        )
        return AccessRoleChange(after, True, revoked_sessions, audit.id)

    def replace_role_permissions(
        self,
        *,
        actor_user_id: str,
        role_id: str,
        permissions: tuple[str, ...],
        expected_lifecycle_version: int,
        as_of: datetime,
    ) -> AccessRoleChange:
        instant = self._validate_clock(as_of)
        target = _scope(role_id, "role_id")
        self._lock()
        actor = self._require_actor(actor_user_id)
        self._validate_permissions(permissions)
        row = self._role_row(target, for_update=True)
        if row is None:
            raise AccessAdministrationError("access_role_not_found", "Role was not found.")
        current = self._role(row)
        if current.lifecycle_version != expected_lifecycle_version:
            raise AccessAdministrationError(
                "access_lifecycle_version_conflict", "Role lifecycle version does not match."
            )
        requested = frozenset(permissions)
        existing = frozenset(current.permissions)
        if requested == existing:
            return AccessRoleChange(current, False, 0, None)
        removed = tuple(sorted(existing - requested))
        added = tuple(sorted(requested - existing))
        if "roles.manage" in removed and self._active_manager_count_excluding_role(target) < 1:
            raise AccessAdministrationError(
                "access_last_manager_forbidden", "The last active roles.manage authority cannot be removed."
            )
        if removed:
            self.connection.execute(
                """UPDATE reconforge.identity_role_permissions
                      SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=%s,
                          revoked_by=%s,revocation_reason_code='access_change'
                    WHERE tenant_id=%s AND role_id=%s AND permission_name=ANY(%s) AND active""",
                (instant, actor, self.tenant_id, target, list(removed)),
            )
        for permission in added:
            self.connection.execute(
                """INSERT INTO reconforge.identity_role_permissions
                       (tenant_id,role_id,permission_name,active,lifecycle_version,granted_at,granted_by)
                   VALUES (%s,%s,%s,TRUE,1,%s,%s)
                   ON CONFLICT (tenant_id,role_id,permission_name) DO UPDATE
                     SET active=TRUE,lifecycle_version=reconforge.identity_role_permissions.lifecycle_version+1,
                         granted_at=EXCLUDED.granted_at,granted_by=EXCLUDED.granted_by,
                         revoked_at=NULL,revoked_by=NULL,revocation_reason_code=NULL""",
                (self.tenant_id, target, permission, instant, actor),
            )
        affected_rows = self.connection.execute(
            """SELECT user_id FROM reconforge.identity_user_roles
               WHERE tenant_id=%s AND role_id=%s AND active ORDER BY user_id""",
            (self.tenant_id, target),
        ).fetchall()
        affected_users = tuple(str(_value(item, "user_id", 0)) for item in affected_rows)
        self.connection.execute(
            """UPDATE reconforge.identity_roles
                  SET lifecycle_version=lifecycle_version+1,updated_at=%s
                WHERE tenant_id=%s AND id=%s AND lifecycle_version=%s""",
            (instant, self.tenant_id, target, expected_lifecycle_version),
        )
        self._increment_users(affected_users)
        revoked_sessions = self._revoke_sessions(affected_users, actor, instant)
        after_row = self._role_row(target)
        if after_row is None:
            raise AccessAdministrationError("access_role_not_found", "Role was not found.")
        after = self._role(after_row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="identity_role_policy",
            object_id=target,
            action="access.role.permissions.replaced",
            before_hash=current.state_digest,
            after_hash=after.state_digest,
            metadata={
                "added_count": len(added),
                "affected_user_count": len(affected_users),
                "removed_count": len(removed),
                "revoked_session_count": revoked_sessions,
                "schema_version": 1,
            },
        )
        return AccessRoleChange(after, True, revoked_sessions, audit.id)

    def _user_assignment(self, user_id: str, *, for_update: bool = False) -> Any | None:
        query = (
            """SELECT u.id,u.username,u.lifecycle_version,
                      ARRAY(SELECT ur.role_id FROM reconforge.identity_user_roles ur
                             JOIN reconforge.identity_roles r
                               ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                            WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active AND r.active
                            ORDER BY ur.role_id),
                      ARRAY(SELECT r.name FROM reconforge.identity_user_roles ur
                             JOIN reconforge.identity_roles r
                               ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                            WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active AND r.active
                            ORDER BY r.name),u.disabled
                 FROM reconforge.identity_users u
                WHERE u.tenant_id=%s AND u.id=%s FOR UPDATE OF u"""
            if for_update
            else """SELECT u.id,u.username,u.lifecycle_version,
                      ARRAY(SELECT ur.role_id FROM reconforge.identity_user_roles ur
                             JOIN reconforge.identity_roles r
                               ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                            WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active AND r.active
                            ORDER BY ur.role_id),
                      ARRAY(SELECT r.name FROM reconforge.identity_user_roles ur
                             JOIN reconforge.identity_roles r
                               ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
                            WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active AND r.active
                            ORDER BY r.name),u.disabled
                 FROM reconforge.identity_users u
                WHERE u.tenant_id=%s AND u.id=%s"""
        )
        return self.connection.execute(query, (self.tenant_id, user_id)).fetchone()

    @staticmethod
    def _assignment_state(row: Any) -> tuple[str, str, int, tuple[str, ...], tuple[str, ...], bool, str]:
        user_id = str(_value(row, "id", 0))
        username = str(_value(row, "username", 1))
        version = int(_value(row, "lifecycle_version", 2))
        role_ids = tuple(str(item) for item in (_value(row, "role_ids", 3) or ()))
        role_names = tuple(str(item) for item in (_value(row, "role_names", 4) or ()))
        disabled = bool(_value(row, "disabled", 5))
        state_digest = _digest(
            {
                "disabled": disabled,
                "lifecycle_version": version,
                "role_ids": list(role_ids),
                "role_names": list(role_names),
                "user_id": user_id,
                "username": username,
            }
        )
        return user_id, username, version, role_ids, role_names, disabled, state_digest

    def replace_user_roles(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        role_ids: tuple[str, ...],
        expected_user_lifecycle_version: int,
        as_of: datetime,
    ) -> UserRoleAssignmentChange:
        instant = self._validate_clock(as_of)
        target = _scope(user_id, "user_id")
        self._lock()
        actor = self._require_actor(actor_user_id)
        role_refs = self._validate_active_roles(role_ids)
        row = self._user_assignment(target, for_update=True)
        if row is None:
            raise AccessAdministrationError("access_user_not_found", "Identity user was not found.")
        before = self._assignment_state(row)
        if before[2] != expected_user_lifecycle_version:
            raise AccessAdministrationError(
                "access_lifecycle_version_conflict", "User lifecycle version does not match."
            )
        requested = frozenset(role_ids)
        existing = frozenset(before[3])
        if requested == existing:
            return UserRoleAssignmentChange(
                user_id=before[0],
                username=before[1],
                lifecycle_version=before[2],
                role_ids=before[3],
                role_names=before[4],
                transitioned=False,
                revoked_sessions=0,
                audit_event_id=None,
                state_digest=before[6],
            )
        if (
            self._active_manager_count_excluding_user(target) < 1
            and not before[5]
            and not self._roles_grant_management(role_ids)
        ):
            raise AccessAdministrationError(
                "access_last_manager_forbidden", "The last active roles.manage authority cannot be removed."
            )
        removed = tuple(sorted(existing - requested))
        added = tuple(sorted(requested - existing))
        if removed:
            self.connection.execute(
                """UPDATE reconforge.identity_user_roles
                      SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=%s,
                          revoked_by=%s,revocation_reason_code='access_change'
                    WHERE tenant_id=%s AND user_id=%s AND role_id=ANY(%s) AND active""",
                (instant, actor, self.tenant_id, target, list(removed)),
            )
        for role_id, _role_name in role_refs:
            if role_id not in added:
                continue
            self.connection.execute(
                """INSERT INTO reconforge.identity_user_roles
                       (tenant_id,user_id,role_id,active,lifecycle_version,granted_at,granted_by)
                   VALUES (%s,%s,%s,TRUE,1,%s,%s)
                   ON CONFLICT (tenant_id,user_id,role_id) DO UPDATE
                     SET active=TRUE,lifecycle_version=reconforge.identity_user_roles.lifecycle_version+1,
                         granted_at=EXCLUDED.granted_at,granted_by=EXCLUDED.granted_by,
                         revoked_at=NULL,revoked_by=NULL,revocation_reason_code=NULL""",
                (self.tenant_id, target, role_id, instant, actor),
            )
        self._increment_users((target,))
        revoked_sessions = self._revoke_sessions((target,), actor, instant)
        after_row = self._user_assignment(target)
        if after_row is None:
            raise AccessAdministrationError("access_user_not_found", "Identity user was not found.")
        after = self._assignment_state(after_row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="identity_user_roles",
            object_id=target,
            action="access.user.roles.replaced",
            before_hash=before[6],
            after_hash=after[6],
            metadata={
                "added_count": len(added),
                "removed_count": len(removed),
                "revoked_session_count": revoked_sessions,
                "schema_version": 1,
            },
        )
        return UserRoleAssignmentChange(
            user_id=after[0],
            username=after[1],
            lifecycle_version=after[2],
            role_ids=after[3],
            role_names=after[4],
            transitioned=True,
            revoked_sessions=revoked_sessions,
            audit_event_id=audit.id,
            state_digest=after[6],
        )
