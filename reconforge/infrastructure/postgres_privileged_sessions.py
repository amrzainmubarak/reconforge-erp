"""Short-lived, session-bound human reauthentication for privileged actions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository

_STEP_UP_TTL = timedelta(minutes=10)

POSTGRES_ACTIVE_ASSURANCE_QUERY = """
SELECT sessions.id,
       (assertions.expires_at IS NOT NULL AND assertions.expires_at > now()) AS step_up_active,
       assertions.expires_at,
       assertions.method
FROM reconforge.identity_sessions sessions
LEFT JOIN LATERAL (
    SELECT expires_at,method
    FROM reconforge.identity_step_up_assertions
    WHERE tenant_id = sessions.tenant_id
      AND session_id = sessions.id
      AND user_id = sessions.user_id
      AND expires_at > now()
    ORDER BY CASE method WHEN 'webauthn_user_verified' THEN 1 ELSE 0 END DESC,
             verified_at DESC,
             id DESC
    LIMIT 1
) assertions ON TRUE
WHERE sessions.tenant_id = %s
  AND sessions.user_id = %s
  AND sessions.token_hash = %s
  AND sessions.revoked_at IS NULL
  AND sessions.expires_at > now()
"""


class PrivilegedSessionError(RuntimeError):
    """Raised when privileged-session state cannot be safely processed."""


@dataclass(frozen=True)
class PrivilegedSessionAssurance:
    """The active assurance snapshot for one authenticated human session."""

    session_id: str
    step_up_active: bool
    step_up_expires_at: str | None
    step_up_method: str | None = None


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PrivilegedSessionError(str(exc)) from exc


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PrivilegedSessionError(str(exc)) from exc


def _token_digest(token: str) -> str:
    if not token:
        raise PrivilegedSessionError("Session token must not be blank.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _utc_text(value: Any) -> str:
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PrivilegedSessionError("Stored privileged-session timestamp is invalid.") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PostgresPrivilegedSessionRepository:
    """Persist immutable password-reauthentication assertions under forced RLS."""

    connection: Any

    def assurance_for_token(
        self, *, tenant_id: str, token: str, user_id: str
    ) -> PrivilegedSessionAssurance | None:
        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        digest = _token_digest(token)
        row = self.connection.execute(POSTGRES_ACTIVE_ASSURANCE_QUERY, (tenant, user, digest)).fetchone()
        if row is None:
            return None
        stored_digest = self.connection.execute(
            "SELECT token_hash FROM reconforge.identity_sessions WHERE tenant_id=%s AND id=%s",
            (tenant, str(_value(row, "id", 0))),
        ).fetchone()
        if stored_digest is None or not hmac.compare_digest(str(_value(stored_digest, "token_hash", 0)), digest):
            return None
        expires = _value(row, "expires_at", 2)
        return PrivilegedSessionAssurance(
            session_id=str(_value(row, "id", 0)),
            step_up_active=bool(_value(row, "step_up_active", 1)),
            step_up_expires_at=_utc_text(expires) if expires is not None else None,
            step_up_method=str(_value(row, "method", 3)) if _value(row, "method", 3) is not None else None,
        )

    def reauthenticate(
        self,
        *,
        tenant_id: str,
        token: str,
        user_id: str,
        username: str,
        password: str,
        request_id: str = "",
    ) -> PrivilegedSessionAssurance | None:
        """Reverify the current human password and append a ten-minute assertion."""

        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        digest = _token_digest(token)
        session = self.connection.execute(
            """
            SELECT id, expires_at
            FROM reconforge.identity_sessions
            WHERE tenant_id=%s AND user_id=%s AND token_hash=%s
              AND revoked_at IS NULL AND expires_at > now()
            FOR UPDATE
            """,
            (tenant, user, digest),
        ).fetchone()
        if session is None:
            return None
        authenticated = PostgresIdentityRepository(self.connection).authenticate_user(
            tenant_id=tenant, username=username, password=password
        )
        if authenticated is None or authenticated.id != user:
            return None
        session_id = str(_value(session, "id", 0))
        session_expires = _value(session, "expires_at", 1)
        if not isinstance(session_expires, datetime):
            session_expires = datetime.fromisoformat(str(session_expires).replace("Z", "+00:00"))
        now = datetime.now(UTC).replace(microsecond=0)
        expires = min(now + _STEP_UP_TTL, session_expires)
        if expires <= now:
            return None
        assertion_id = f"sup-{secrets.token_hex(16)}"
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_step_up_assertions
                (tenant_id,id,session_id,user_id,method,verified_at,expires_at,request_id)
            VALUES (%s,%s,%s,%s,'password_reauthentication',%s,%s,%s)
            """,
            (tenant, assertion_id, session_id, user, now, expires, request_id[:128]),
        )
        return PrivilegedSessionAssurance(session_id, True, _utc_text(expires), "password_reauthentication")

    def record_webauthn_verification(
        self,
        *,
        tenant_id: str,
        token: str,
        user_id: str,
        credential_id: str,
        request_id: str = "",
    ) -> PrivilegedSessionAssurance | None:
        """Append a user-verified WebAuthn assertion for the current session."""

        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        session = self.connection.execute(
            """
            SELECT id,expires_at FROM reconforge.identity_sessions
            WHERE tenant_id=%s AND user_id=%s AND token_hash=%s
              AND revoked_at IS NULL AND expires_at>now()
            FOR UPDATE
            """,
            (tenant, user, _token_digest(token)),
        ).fetchone()
        if session is None:
            return None
        session_id = str(_value(session, "id", 0))
        session_expires = _value(session, "expires_at", 1)
        if not isinstance(session_expires, datetime):
            session_expires = datetime.fromisoformat(str(session_expires).replace("Z", "+00:00"))
        now = datetime.now(UTC).replace(microsecond=0)
        expires = min(now + _STEP_UP_TTL, session_expires)
        if expires <= now:
            return None
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_step_up_assertions
                (tenant_id,id,session_id,user_id,method,verified_at,expires_at,request_id,credential_id)
            VALUES (%s,%s,%s,%s,'webauthn_user_verified',%s,%s,%s,%s)
            """,
            (
                tenant,
                f"sup-{secrets.token_hex(16)}",
                session_id,
                user,
                now,
                expires,
                request_id[:128],
                credential_id,
            ),
        )
        return PrivilegedSessionAssurance(session_id, True, _utc_text(expires), "webauthn_user_verified")


POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.identity_step_up_assertions (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method = 'password_reauthentication'),
    verified_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    request_id TEXT NOT NULL DEFAULT '' CHECK (length(request_id) <= 128),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, session_id) REFERENCES reconforge.identity_sessions(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, user_id) REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE CASCADE,
    CHECK (expires_at > verified_at),
    CHECK (expires_at <= verified_at + interval '15 minutes')
);
CREATE INDEX IF NOT EXISTS idx_identity_step_up_active
    ON reconforge.identity_step_up_assertions (tenant_id, session_id, expires_at DESC);
ALTER TABLE reconforge.identity_step_up_assertions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_step_up_assertions FORCE ROW LEVEL SECURITY;
DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='reconforge'
          AND tablename='identity_step_up_assertions' AND policyname='tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.identity_step_up_assertions
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END
$reconforge$;
CREATE OR REPLACE FUNCTION reconforge.reject_step_up_assertion_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'step-up assertions are append-only';
END;
$$;
DROP TRIGGER IF EXISTS identity_step_up_assertions_append_only ON reconforge.identity_step_up_assertions;
CREATE TRIGGER identity_step_up_assertions_append_only
BEFORE UPDATE OR DELETE ON reconforge.identity_step_up_assertions
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_step_up_assertion_mutation();
"""
