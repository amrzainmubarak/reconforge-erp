"""Tenant-scoped PostgreSQL identity, RBAC, and session repository.

This module is the server identity foundation.  It deliberately does not
reuse SQLite connections or trust a caller-provided actor label.  Passwords
are verified with the existing PBKDF2-HMAC-SHA256 implementation, only token
hashes are persisted, and all methods use caller-owned transactions.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from reconforge.auth.models import LocalUser
from reconforge.auth.passwords import PasswordHash, hash_password, verify_password
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.utils.time import utc_now_text

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@+-]{0,159}$")
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SESSION_TTL = timedelta(hours=8)
_SESSION_ACTIVITY_INTERVAL = timedelta(minutes=5)
_MAX_LOGIN_FAILURES = 8
_LOCKOUT_DURATION = timedelta(minutes=15)


class PostgresIdentityValidationError(ValueError):
    """Raised when an identity input is invalid."""


class PostgresIdentityError(RuntimeError):
    """Raised for safe repository-level identity failures."""


@dataclass(frozen=True)
class PostgresSession:
    """A newly issued session; the raw token is returned only once."""

    id: str
    user_id: str
    token: str
    expires_at: str


@dataclass(frozen=True)
class _StoredUser:
    user: LocalUser
    password: PasswordHash
    locked_until: datetime | None


def _scope_id(value: str, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresIdentityValidationError(str(exc)) from exc
    if not _ID_PATTERN.fullmatch(normalized):
        raise PostgresIdentityValidationError(f"{field_name} has an invalid identifier.")
    return normalized


def _tenant_id(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresIdentityValidationError(str(exc)) from exc


def _text(value: object, field_name: str, *, maximum: int = 255) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PostgresIdentityValidationError(f"{field_name} must not be blank.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise PostgresIdentityValidationError(f"{field_name} must contain printable characters only.")
    if len(normalized) > maximum:
        raise PostgresIdentityValidationError(f"{field_name} must be at most {maximum} characters.")
    return " ".join(normalized.split())


def _optional_text(value: object, field_name: str, *, maximum: int = 255) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _text(value, field_name, maximum=maximum)


def _username(value: str) -> str:
    normalized = _text(value, "username", maximum=160).casefold()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise PostgresIdentityValidationError("username contains unsupported characters.")
    return normalized


def _role(value: str) -> str:
    normalized = _text(value, "role_name", maximum=64).casefold()
    if not _ROLE_PATTERN.fullmatch(normalized):
        raise PostgresIdentityValidationError("role_name contains unsupported characters.")
    return normalized


def _permission(value: str) -> str:
    normalized = _text(value, "permission_name", maximum=128).casefold()
    if not _PERMISSION_PATTERN.fullmatch(normalized):
        raise PostgresIdentityValidationError("permission_name contains unsupported characters.")
    return normalized


def _token_hash(token: str) -> str:
    if not token:
        raise PostgresIdentityValidationError("token must not be blank.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _timestamp(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostgresIdentityError("Stored identity timestamp is invalid.") from exc


def _timestamp_text(value: object | None) -> str | None:
    parsed = _timestamp(value)
    if parsed is None:
        return None
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _user_from_row(row: Any) -> _StoredUser:
    password = PasswordHash(
        algorithm=str(_row_value(row, "password_algorithm", 7)),
        iterations=int(_row_value(row, "password_iterations", 6)),
        salt_hex=str(_row_value(row, "password_salt", 5)),
        hash_hex=str(_row_value(row, "password_hash", 4)),
    )
    # The tenant identifier is returned after ``locked_until`` in the user
    # projection.  Keep the positional fallback aligned with
    # ``_USER_COLUMNS`` and the joined session projection below.
    locked_until = _timestamp(_row_value(row, "locked_until", 13))
    user = LocalUser(
        id=str(_row_value(row, "id", 0)),
        username=str(_row_value(row, "username", 1)),
        display_name=str(_row_value(row, "display_name", 2)),
        email=str(_row_value(row, "email", 3)) if _row_value(row, "email", 3) is not None else None,
        disabled=bool(_row_value(row, "disabled", 8)),
        created_at=str(_timestamp_text(_row_value(row, "created_at", 9)) or ""),
        password_changed_at=_timestamp_text(_row_value(row, "password_changed_at", 10)),
        failed_login_count=int(_row_value(row, "failed_login_count", 12) or 0),
        locked_until=_timestamp_text(_row_value(row, "locked_until", 13)),
    )
    return _StoredUser(user=user, password=password, locked_until=locked_until)


@dataclass(frozen=True)
class PostgresIdentityRepository:
    """Persist tenant-scoped users, RBAC assignments, and hashed sessions."""

    connection: Any

    _USER_COLUMNS = (
        "id",
        "username",
        "display_name",
        "email",
        "password_hash",
        "password_salt",
        "password_iterations",
        "password_algorithm",
        "disabled",
        "created_at",
        "password_changed_at",
        "updated_at",
        "failed_login_count",
        "locked_until",
        "tenant_id",
    )

    def create_role(self, *, tenant_id: str, role_name: str, description: str = "") -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        role = _role(role_name)
        role_id = f"role-{hashlib.sha256(role.encode('utf-8')).hexdigest()[:32]}"
        role_description = _optional_text(description, "role description", maximum=500) or ""
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.identity_roles (tenant_id, id, name, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, name) DO NOTHING
            RETURNING tenant_id, id, name, description, created_at, updated_at
            """,
            (tenant, role_id, role, role_description),
        )
        row = cursor.fetchone()
        if row is None:
            row = self.connection.execute(
                """SELECT tenant_id,id,name,description,created_at,updated_at
                   FROM reconforge.identity_roles WHERE tenant_id=%s AND name=%s""",
                (tenant, role),
            ).fetchone()
        if row is None:
            raise PostgresIdentityError("Identity role was not returned after bootstrap.")
        return (
            dict(row)
            if isinstance(row, Mapping)
            else dict(zip(("tenant_id", "id", "name", "description", "created_at", "updated_at"), row, strict=True))
        )

    def create_permission(self, *, tenant_id: str, permission_name: str, description: str = "") -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        permission = _permission(permission_name)
        permission_description = _optional_text(description, "permission description", maximum=500) or ""
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.identity_permissions (tenant_id, name, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, name) DO NOTHING
            RETURNING tenant_id, name, description, created_at, updated_at
            """,
            (tenant, permission, permission_description),
        )
        row = cursor.fetchone()
        if row is None:
            row = self.connection.execute(
                """SELECT tenant_id,name,description,created_at,updated_at
                   FROM reconforge.identity_permissions WHERE tenant_id=%s AND name=%s""",
                (tenant, permission),
            ).fetchone()
        if row is None:
            raise PostgresIdentityError("Identity permission was not returned after bootstrap.")
        return (
            dict(row)
            if isinstance(row, Mapping)
            else dict(zip(("tenant_id", "name", "description", "created_at", "updated_at"), row, strict=True))
        )

    def grant_permission(self, *, tenant_id: str, role_name: str, permission_name: str) -> None:
        tenant = _tenant_id(tenant_id)
        role = _role(role_name)
        permission = _permission(permission_name)
        reference = self.connection.execute(
            """
            SELECT roles.id, permissions.name
            FROM reconforge.identity_roles roles
            JOIN reconforge.identity_permissions permissions
              ON permissions.tenant_id = roles.tenant_id AND permissions.name = %s
            WHERE roles.tenant_id = %s AND roles.name = %s AND roles.active
            """,
            (permission, tenant, role),
        ).fetchone()
        if reference is None:
            raise PostgresIdentityError("Identity role or permission was not found.")
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_role_permissions (tenant_id, role_id, permission_name)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (tenant, _row_value(reference, "id", 0), _row_value(reference, "name", 1)),
        )

    def create_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        username: str,
        password: str,
        role_name: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> LocalUser:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(user_id, "user_id")
        normalized_username = _username(username)
        role = _role(role_name)
        user_display_name = _text(display_name or normalized_username, "display_name")
        user_email = _optional_text(email, "email", maximum=320)
        role_reference = self.connection.execute(
            "SELECT id FROM reconforge.identity_roles WHERE tenant_id = %s AND name = %s AND active",
            (tenant, role),
        ).fetchone()
        if role_reference is None:
            raise PostgresIdentityError("Identity role was not found.")
        password_hash = hash_password(password)
        now = utc_now_text()
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.identity_users
                (tenant_id, id, username, display_name, email, password_hash, password_salt,
                 password_iterations, password_algorithm, password_changed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, username, display_name, email, password_hash, password_salt,
                      password_iterations, password_algorithm, disabled, created_at,
                      password_changed_at, updated_at, failed_login_count, locked_until, tenant_id
            """,
            (
                tenant,
                identifier,
                normalized_username,
                user_display_name,
                user_email,
                password_hash.hash_hex,
                password_hash.salt_hex,
                password_hash.iterations,
                password_hash.algorithm,
                now,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresIdentityError("Identity user was not returned after creation.")
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_user_roles (tenant_id, user_id, role_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (tenant, identifier, _row_value(role_reference, "id", 0)),
        )
        return _user_from_row(row).user

    def get_user(self, *, tenant_id: str, username: str) -> LocalUser | None:
        tenant = _tenant_id(tenant_id)
        normalized_username = _username(username)
        cursor = self.connection.execute(
            """
            SELECT id, username, display_name, email, password_hash, password_salt,
                   password_iterations, password_algorithm, disabled, created_at,
                   password_changed_at, updated_at, failed_login_count, locked_until, tenant_id
            FROM reconforge.identity_users
            WHERE tenant_id = %s AND username = %s
            """,
            (tenant, normalized_username),
        )
        row = cursor.fetchone()
        return _user_from_row(row).user if row is not None else None

    def get_user_by_id(self, *, tenant_id: str, user_id: str) -> LocalUser | None:
        """Return one active-identity projection by immutable user id."""

        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(user_id, "user_id")
        cursor = self.connection.execute(
            """
            SELECT id, username, display_name, email, password_hash, password_salt,
                   password_iterations, password_algorithm, disabled, created_at,
                   password_changed_at, updated_at, failed_login_count, locked_until, tenant_id
            FROM reconforge.identity_users
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        row = cursor.fetchone()
        return _user_from_row(row).user if row is not None else None

    def authenticate_user(self, *, tenant_id: str, username: str, password: str) -> LocalUser | None:
        tenant = _tenant_id(tenant_id)
        normalized_username = _username(username)
        if not password:
            return None
        cursor = self.connection.execute(
            """
            SELECT id, username, display_name, email, password_hash, password_salt,
                   password_iterations, password_algorithm, disabled, created_at,
                   password_changed_at, updated_at, failed_login_count, locked_until, tenant_id
            FROM reconforge.identity_users
            WHERE tenant_id = %s AND username = %s
            FOR UPDATE
            """,
            (tenant, normalized_username),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        stored = _user_from_row(row)
        now = datetime.now(UTC)
        if stored.user.disabled or (stored.locked_until is not None and stored.locked_until > now):
            return None
        if verify_password(password, stored.password):
            self.connection.execute(
                "UPDATE reconforge.identity_users SET failed_login_count = 0, locked_until = NULL, updated_at = now() WHERE tenant_id = %s AND id = %s",
                (tenant, stored.user.id),
            )
            return stored.user
        next_failures = stored.user.failed_login_count + 1
        locked_until = now + _LOCKOUT_DURATION if next_failures >= _MAX_LOGIN_FAILURES else None
        self.connection.execute(
            """
            UPDATE reconforge.identity_users
            SET failed_login_count = %s, locked_until = %s, updated_at = now()
            WHERE tenant_id = %s AND id = %s
            """,
            (next_failures, locked_until, tenant, stored.user.id),
        )
        return None

    def user_roles(self, *, tenant_id: str, user_id: str) -> list[str]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(user_id, "user_id")
        cursor = self.connection.execute(
            """
            SELECT roles.name
            FROM reconforge.identity_user_roles assignments
            JOIN reconforge.identity_roles roles
              ON roles.tenant_id = assignments.tenant_id AND roles.id = assignments.role_id
            WHERE assignments.tenant_id = %s AND assignments.user_id = %s
              AND assignments.active AND roles.active
            ORDER BY roles.name
            """,
            (tenant, identifier),
        )
        return [str(_row_value(row, "name", 0)) for row in cursor.fetchall()]

    def user_has_permission(self, *, tenant_id: str, user_id: str, permission_name: str) -> bool:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(user_id, "user_id")
        permission = _permission(permission_name)
        row = self.connection.execute(
            """
            SELECT 1
            FROM reconforge.identity_user_roles assignments
            JOIN reconforge.identity_role_permissions role_permissions
              ON role_permissions.tenant_id = assignments.tenant_id AND role_permissions.role_id = assignments.role_id
            WHERE assignments.tenant_id = %s
              AND assignments.user_id = %s
              AND role_permissions.permission_name = %s
              AND assignments.active AND role_permissions.active
              AND EXISTS (
                    SELECT 1 FROM reconforge.identity_roles roles
                     WHERE roles.tenant_id=assignments.tenant_id
                       AND roles.id=assignments.role_id AND roles.active
              )
            LIMIT 1
            """,
            (tenant, identifier, permission),
        ).fetchone()
        return row is not None

    def user_permissions(self, *, tenant_id: str, user_id: str) -> frozenset[str]:
        """Return the deterministic permission snapshot for an authenticated user."""

        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(user_id, "user_id")
        cursor = self.connection.execute(
            """
            SELECT DISTINCT role_permissions.permission_name
            FROM reconforge.identity_user_roles assignments
            JOIN reconforge.identity_role_permissions role_permissions
              ON role_permissions.tenant_id = assignments.tenant_id
             AND role_permissions.role_id = assignments.role_id
            WHERE assignments.tenant_id = %s AND assignments.user_id = %s
              AND assignments.active AND role_permissions.active
              AND EXISTS (
                    SELECT 1 FROM reconforge.identity_roles roles
                     WHERE roles.tenant_id=assignments.tenant_id
                       AND roles.id=assignments.role_id AND roles.active
              )
            ORDER BY role_permissions.permission_name
            """,
            (tenant, identifier),
        )
        return frozenset(str(_row_value(row, "permission_name", 0)) for row in cursor.fetchall())

    def create_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> PostgresSession:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(user_id, "user_id")
        raw_token = secrets.token_urlsafe(32)
        session_id = _scope_id(f"ses-{secrets.token_hex(16)}", "session_id")
        now = datetime.now(UTC).replace(microsecond=0)
        expires = now + _SESSION_TTL
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_sessions
                (tenant_id, id, user_id, token_hash, created_at, expires_at, client_ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant,
                session_id,
                identifier,
                _token_hash(raw_token),
                now,
                expires,
                _optional_text(client_ip, "client_ip", maximum=64),
                _optional_text(user_agent, "user_agent", maximum=512),
            ),
        )
        return PostgresSession(
            id=session_id,
            user_id=identifier,
            token=raw_token,
            expires_at=expires.isoformat().replace("+00:00", "Z"),
        )

    def authenticate_token(self, *, tenant_id: str, token: str) -> LocalUser | None:
        tenant = _tenant_id(tenant_id)
        digest = _token_hash(token)
        cursor = self.connection.execute(
            """
            SELECT users.id, users.username, users.display_name, users.email, users.password_hash,
                   users.password_salt, users.password_iterations, users.password_algorithm,
                   users.disabled, users.created_at, users.password_changed_at, users.updated_at,
                   users.failed_login_count, users.locked_until, users.tenant_id,
                   sessions.id, sessions.expires_at, sessions.revoked_at, sessions.last_used_at, sessions.token_hash
            FROM reconforge.identity_sessions sessions
            JOIN reconforge.identity_users users
              ON users.tenant_id = sessions.tenant_id AND users.id = sessions.user_id
            WHERE sessions.tenant_id = %s AND sessions.token_hash = %s
            """,
            (tenant, digest),
        )
        row = cursor.fetchone()
        if row is None or not hmac.compare_digest(str(_row_value(row, "token_hash", 19)), digest):
            return None
        now = datetime.now(UTC)
        expires_at = _timestamp(_row_value(row, "expires_at", 16))
        revoked_at = _timestamp(_row_value(row, "revoked_at", 17))
        if expires_at is None or expires_at <= now or revoked_at is not None:
            return None
        stored = _user_from_row(row)
        if stored.user.disabled:
            return None
        last_used = _timestamp(_row_value(row, "last_used_at", 18))
        if last_used is None or last_used <= now - _SESSION_ACTIVITY_INTERVAL:
            self.connection.execute(
                "UPDATE reconforge.identity_sessions SET last_used_at = now() WHERE tenant_id = %s AND id = %s",
                (tenant, str(_row_value(row, "id", 15))),
            )
        return stored.user

    def revoke_token(self, *, tenant_id: str, token: str) -> bool:
        tenant = _tenant_id(tenant_id)
        digest = _token_hash(token)
        cursor = self.connection.execute(
            """
            UPDATE reconforge.identity_sessions
            SET revoked_at = now(),
                revocation_reason_code = 'user_logout',
                revoked_by = user_id,
                lifecycle_version = lifecycle_version + 1
            WHERE tenant_id = %s AND token_hash = %s AND revoked_at IS NULL
            RETURNING id
            """,
            (tenant, digest),
        )
        return cursor.fetchone() is not None


POSTGRES_IDENTITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.identity_roles (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    lifecycle_version BIGINT NOT NULL DEFAULT 1,
    created_by TEXT,
    retired_at TIMESTAMPTZ,
    retired_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name),
    CONSTRAINT identity_roles_lifecycle_version_positive CHECK (lifecycle_version >= 1),
    CONSTRAINT identity_roles_retirement_state_consistent CHECK (
        (active AND retired_at IS NULL AND retired_by IS NULL)
        OR (NOT active AND retired_at IS NOT NULL AND retired_by IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.identity_permissions (
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, name),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.identity_users (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_iterations INTEGER NOT NULL CHECK (password_iterations >= 100000),
    password_algorithm TEXT NOT NULL CHECK (password_algorithm = 'pbkdf2_sha256'),
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    password_changed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    failed_login_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until TIMESTAMPTZ,
    lifecycle_version BIGINT NOT NULL DEFAULT 1,
    disabled_at TIMESTAMPTZ,
    disabled_by TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, username),
    CONSTRAINT identity_users_lifecycle_version_positive CHECK (lifecycle_version >= 1),
    CONSTRAINT identity_users_disabled_state_consistent CHECK (
        (disabled AND disabled_at IS NOT NULL)
        OR (NOT disabled AND disabled_at IS NULL AND disabled_by IS NULL)
    ),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.identity_user_roles (
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    lifecycle_version BIGINT NOT NULL DEFAULT 1,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by TEXT,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    revocation_reason_code TEXT,
    PRIMARY KEY (tenant_id, user_id, role_id),
    CONSTRAINT identity_user_roles_lifecycle_version_positive CHECK (lifecycle_version >= 1),
    CONSTRAINT identity_user_roles_revocation_reason_closed CHECK (
        revocation_reason_code IS NULL OR revocation_reason_code IN (
            'access_change','administrative_cleanup','role_retired','security_response','user_request'
        )
    ),
    CONSTRAINT identity_user_roles_state_consistent CHECK (
        (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason_code IS NULL)
        OR (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
            AND revocation_reason_code IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id, user_id) REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, role_id) REFERENCES reconforge.identity_roles(tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.identity_role_permissions (
    tenant_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    permission_name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    lifecycle_version BIGINT NOT NULL DEFAULT 1,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by TEXT,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    revocation_reason_code TEXT,
    PRIMARY KEY (tenant_id, role_id, permission_name),
    CONSTRAINT identity_role_permissions_lifecycle_version_positive CHECK (lifecycle_version >= 1),
    CONSTRAINT identity_role_permissions_revocation_reason_closed CHECK (
        revocation_reason_code IS NULL OR revocation_reason_code IN (
            'access_change','administrative_cleanup','role_retired','security_response','user_request'
        )
    ),
    CONSTRAINT identity_role_permissions_state_consistent CHECK (
        (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason_code IS NULL)
        OR (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
            AND revocation_reason_code IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id, role_id) REFERENCES reconforge.identity_roles(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, permission_name) REFERENCES reconforge.identity_permissions(tenant_id, name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.identity_sessions (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    client_ip TEXT,
    user_agent TEXT,
    lifecycle_version BIGINT NOT NULL DEFAULT 1,
    revocation_reason_code TEXT,
    revoked_by TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, token_hash),
    CONSTRAINT identity_sessions_lifecycle_version_positive CHECK (lifecycle_version >= 1),
    CONSTRAINT identity_sessions_revocation_reason_closed CHECK (
        revocation_reason_code IS NULL OR revocation_reason_code IN (
            'access_change','administrative_cleanup','legacy_or_user_logout',
            'scim_deactivation','security_response','user_disabled','user_logout','user_request'
        )
    ),
    CONSTRAINT identity_sessions_revocation_state_consistent CHECK (
        (revoked_at IS NULL AND revocation_reason_code IS NULL AND revoked_by IS NULL)
        OR (revoked_at IS NOT NULL AND revocation_reason_code IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id, user_id) REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_identity_sessions_active
    ON reconforge.identity_sessions (tenant_id, token_hash, expires_at, revoked_at);
CREATE INDEX IF NOT EXISTS idx_identity_users_admin_page
    ON reconforge.identity_users (tenant_id, username, id);
CREATE INDEX IF NOT EXISTS idx_identity_sessions_admin_page
    ON reconforge.identity_sessions (tenant_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_identity_users_username
    ON reconforge.identity_users (tenant_id, username);
CREATE INDEX IF NOT EXISTS idx_identity_user_roles_user
    ON reconforge.identity_user_roles (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_identity_role_permissions_role
    ON reconforge.identity_role_permissions (tenant_id, role_id, permission_name);
CREATE INDEX IF NOT EXISTS idx_identity_roles_admin_page
    ON reconforge.identity_roles (tenant_id, active, name, id);
CREATE INDEX IF NOT EXISTS idx_identity_user_roles_active
    ON reconforge.identity_user_roles (tenant_id, user_id, active, role_id);
CREATE INDEX IF NOT EXISTS idx_identity_role_permissions_active
    ON reconforge.identity_role_permissions (tenant_id, role_id, active, permission_name);

ALTER TABLE reconforge.identity_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_permissions FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_users FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_role_permissions FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_sessions FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'identity_roles', 'identity_permissions', 'identity_users',
        'identity_user_roles', 'identity_role_permissions', 'identity_sessions'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
             WHERE schemaname = 'reconforge' AND tablename = table_name AND policyname = 'tenant_scope'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
                table_name
            );
        END IF;
    END LOOP;
END
$reconforge$;
"""
