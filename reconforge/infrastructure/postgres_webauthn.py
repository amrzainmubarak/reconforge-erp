"""Forced-RLS WebAuthn challenge, public-key credential, and evidence storage."""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id

Ceremony = Literal["registration", "authentication"]
_CHALLENGE_TTL = timedelta(minutes=5)


class WebAuthnRepositoryError(RuntimeError):
    """Raised when WebAuthn persistence cannot safely satisfy the ceremony."""


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise WebAuthnRepositoryError(str(exc)) from exc


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise WebAuthnRepositoryError(str(exc)) from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise WebAuthnRepositoryError("Stored WebAuthn binary value is invalid.") from exc
    if _b64(decoded) != value:
        raise WebAuthnRepositoryError("Stored WebAuthn binary value is not canonical base64url.")
    return decoded


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


@dataclass(frozen=True)
class WebAuthnChallenge:
    id: str
    challenge: bytes
    ceremony: Ceremony
    user_id: str
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class WebAuthnCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: tuple[str, ...]
    device_type: str
    backed_up: bool
    label: str


@dataclass(frozen=True)
class PostgresWebAuthnRepository:
    connection: Any

    def issue_challenge(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        ceremony: Ceremony,
        request_id: str = "",
    ) -> WebAuthnChallenge:
        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        session = _scope(session_id, "session_id")
        if ceremony not in {"registration", "authentication"}:
            raise WebAuthnRepositoryError("Unsupported WebAuthn ceremony.")
        self.connection.execute(
            "DELETE FROM reconforge.identity_webauthn_challenges WHERE tenant_id=%s AND expires_at<=now()",
            (tenant,),
        )
        active = self.connection.execute(
            "SELECT COUNT(*) FROM reconforge.identity_webauthn_challenges "
            "WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND consumed_at IS NULL AND expires_at>now()",
            (tenant, user, session),
        ).fetchone()
        if active is not None and int(_value(active, "count", 0)) >= 8:
            raise WebAuthnRepositoryError("Too many active WebAuthn challenges.")
        now = datetime.now(UTC).replace(microsecond=0)
        result = WebAuthnChallenge(
            id=f"wch-{secrets.token_hex(16)}",
            challenge=secrets.token_bytes(32),
            ceremony=ceremony,
            user_id=user,
            session_id=session,
            expires_at=now + _CHALLENGE_TTL,
        )
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_webauthn_challenges
                (tenant_id,id,user_id,session_id,ceremony,challenge,created_at,expires_at,request_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (tenant, result.id, user, session, ceremony, _b64(result.challenge), now, result.expires_at, request_id[:128]),
        )
        self._event(tenant, user, "challenge_issued", request_id=request_id)
        return result

    def consume_challenge(
        self,
        *,
        tenant_id: str,
        challenge_id: str,
        user_id: str,
        session_id: str,
        ceremony: Ceremony,
        request_id: str = "",
    ) -> WebAuthnChallenge:
        tenant = _tenant(tenant_id)
        row = self.connection.execute(
            """
            UPDATE reconforge.identity_webauthn_challenges
            SET consumed_at=clock_timestamp()
            WHERE tenant_id=%s AND id=%s AND user_id=%s AND session_id=%s AND ceremony=%s
              AND consumed_at IS NULL AND expires_at>now()
            RETURNING id,challenge,ceremony,user_id,session_id,expires_at
            """,
            (
                tenant,
                _scope(challenge_id, "challenge_id"),
                _scope(user_id, "user_id"),
                _scope(session_id, "session_id"),
                ceremony,
            ),
        ).fetchone()
        if row is None:
            raise WebAuthnRepositoryError("WebAuthn challenge is invalid, expired, or already consumed.")
        self._event(tenant, str(_value(row, "user_id", 3)), "challenge_consumed", request_id=request_id)
        return WebAuthnChallenge(
            id=str(_value(row, "id", 0)),
            challenge=_unb64(str(_value(row, "challenge", 1))),
            ceremony=str(_value(row, "ceremony", 2)),  # type: ignore[arg-type]
            user_id=str(_value(row, "user_id", 3)),
            session_id=str(_value(row, "session_id", 4)),
            expires_at=_value(row, "expires_at", 5),
        )

    def credentials_for_user(self, *, tenant_id: str, user_id: str) -> tuple[WebAuthnCredential, ...]:
        rows = self.connection.execute(
            """
            SELECT credential_id,public_key,sign_count,transports,device_type,backed_up,label
            FROM reconforge.identity_webauthn_credentials
            WHERE tenant_id=%s AND user_id=%s AND disabled_at IS NULL
            ORDER BY created_at,credential_id
            """,
            (_tenant(tenant_id), _scope(user_id, "user_id")),
        ).fetchall()
        return tuple(self._credential(row) for row in rows)

    def credential_for_user(
        self, *, tenant_id: str, user_id: str, credential_id: bytes
    ) -> WebAuthnCredential | None:
        row = self.connection.execute(
            """
            SELECT credential_id,public_key,sign_count,transports,device_type,backed_up,label
            FROM reconforge.identity_webauthn_credentials
            WHERE tenant_id=%s AND user_id=%s AND credential_id=%s AND disabled_at IS NULL
            """,
            (_tenant(tenant_id), _scope(user_id, "user_id"), _b64(credential_id)),
        ).fetchone()
        return self._credential(row) if row is not None else None

    def register_credential(
        self,
        *,
        tenant_id: str,
        user_id: str,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        transports: tuple[str, ...],
        device_type: str,
        backed_up: bool,
        label: str,
        request_id: str = "",
    ) -> WebAuthnCredential:
        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        clean_label = label.strip()
        allowed_transports = {"ble", "cable", "hybrid", "internal", "nfc", "smart-card", "usb"}
        if not 1 <= len(clean_label) <= 80 or any(ord(char) < 32 for char in clean_label):
            raise WebAuthnRepositoryError("Credential label must contain 1-80 printable characters.")
        if sign_count < 0 or len(credential_id) > 1024 or not credential_id or len(public_key) > 4096 or not public_key:
            raise WebAuthnRepositoryError("Verified WebAuthn credential material is outside supported bounds.")
        if len(transports) > 8 or len(set(transports)) != len(transports) or set(transports) - allowed_transports:
            raise WebAuthnRepositoryError("Credential transports are invalid or unsupported.")
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_webauthn_credentials
                (tenant_id,credential_id,user_id,public_key,sign_count,transports,device_type,backed_up,label)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
            """,
            (
                tenant,
                _b64(credential_id),
                user,
                _b64(public_key),
                sign_count,
                json.dumps(list(transports), separators=(",", ":")),
                device_type,
                backed_up,
                clean_label,
            ),
        )
        self._event(tenant, user, "credential_registered", credential_id=_b64(credential_id), request_id=request_id)
        result = self.credential_for_user(tenant_id=tenant, user_id=user, credential_id=credential_id)
        if result is None:
            raise WebAuthnRepositoryError("Registered WebAuthn credential could not be reloaded.")
        return result

    def record_authentication(
        self,
        *,
        tenant_id: str,
        user_id: str,
        credential_id: bytes,
        previous_sign_count: int,
        new_sign_count: int,
        device_type: str,
        backed_up: bool,
        request_id: str = "",
    ) -> None:
        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        updated = self.connection.execute(
            """
            UPDATE reconforge.identity_webauthn_credentials
            SET sign_count=%s,device_type=%s,backed_up=%s,last_used_at=now(),version=version+1
            WHERE tenant_id=%s AND user_id=%s AND credential_id=%s AND disabled_at IS NULL AND sign_count=%s
              AND (%s=0 OR %s>%s)
            """,
            (
                new_sign_count,
                device_type,
                backed_up,
                tenant,
                user,
                _b64(credential_id),
                previous_sign_count,
                new_sign_count,
                new_sign_count,
                previous_sign_count,
            ),
        )
        if updated.rowcount != 1:
            raise WebAuthnRepositoryError("WebAuthn signature counter is stale or did not advance safely.")
        self._event(tenant, user, "authentication_verified", credential_id=_b64(credential_id), request_id=request_id)

    @staticmethod
    def _credential(row: Any) -> WebAuthnCredential:
        transports = _value(row, "transports", 3)
        if not isinstance(transports, list):
            raise WebAuthnRepositoryError("Stored WebAuthn transports are invalid.")
        return WebAuthnCredential(
            credential_id=_unb64(str(_value(row, "credential_id", 0))),
            public_key=_unb64(str(_value(row, "public_key", 1))),
            sign_count=int(_value(row, "sign_count", 2)),
            transports=tuple(str(item) for item in transports),
            device_type=str(_value(row, "device_type", 4)),
            backed_up=bool(_value(row, "backed_up", 5)),
            label=str(_value(row, "label", 6)),
        )

    def _event(
        self,
        tenant_id: str,
        user_id: str,
        action: str,
        *,
        credential_id: str | None = None,
        request_id: str = "",
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.identity_webauthn_events
                (tenant_id,id,user_id,action,credential_id,request_id)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (tenant_id, f"wve-{secrets.token_hex(16)}", user_id, action, credential_id, request_id[:128]),
        )


POSTGRES_WEBAUTHN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.identity_webauthn_challenges (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ceremony TEXT NOT NULL CHECK (ceremony IN ('registration','authentication')),
    challenge TEXT NOT NULL CHECK (challenge ~ '^[A-Za-z0-9_-]{43}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    request_id TEXT NOT NULL DEFAULT '' CHECK (length(request_id)<=128),
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,user_id) REFERENCES reconforge.identity_users(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,session_id) REFERENCES reconforge.identity_sessions(tenant_id,id) ON DELETE CASCADE,
    CHECK (expires_at>created_at AND expires_at<=created_at+interval '5 minutes'),
    CHECK (consumed_at IS NULL OR consumed_at>=created_at)
);
CREATE TABLE IF NOT EXISTS reconforge.identity_webauthn_credentials (
    tenant_id TEXT NOT NULL,
    credential_id TEXT NOT NULL CHECK (credential_id ~ '^[A-Za-z0-9_-]+$' AND length(credential_id)<=1366),
    user_id TEXT NOT NULL,
    public_key TEXT NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]+$' AND length(public_key)<=5462),
    sign_count BIGINT NOT NULL DEFAULT 0 CHECK (sign_count>=0),
    transports JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(transports)='array' AND jsonb_array_length(transports)<=8),
    device_type TEXT NOT NULL CHECK (device_type IN ('single_device','multi_device')),
    backed_up BOOLEAN NOT NULL,
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version>=1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id,credential_id),
    FOREIGN KEY (tenant_id,user_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.identity_webauthn_events (
    tenant_id TEXT NOT NULL,
    event_sequence BIGINT GENERATED ALWAYS AS IDENTITY,
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('challenge_issued','challenge_consumed','credential_registered','authentication_verified','credential_disabled')),
    credential_id TEXT,
    request_id TEXT NOT NULL DEFAULT '' CHECK (length(request_id)<=128),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,user_id) REFERENCES reconforge.identity_users(tenant_id,id),
    FOREIGN KEY (tenant_id,credential_id) REFERENCES reconforge.identity_webauthn_credentials(tenant_id,credential_id)
);
CREATE INDEX IF NOT EXISTS idx_webauthn_challenge_active ON reconforge.identity_webauthn_challenges(tenant_id,user_id,session_id,expires_at);
CREATE INDEX IF NOT EXISTS idx_webauthn_credential_user ON reconforge.identity_webauthn_credentials(tenant_id,user_id,disabled_at);
ALTER TABLE reconforge.identity_webauthn_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_webauthn_challenges FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_webauthn_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_webauthn_credentials FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_webauthn_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.identity_webauthn_events FORCE ROW LEVEL SECURITY;
DO $reconforge$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['identity_webauthn_challenges','identity_webauthn_credentials','identity_webauthn_events'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
            EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
        END IF;
    END LOOP;
END
$reconforge$;
CREATE OR REPLACE FUNCTION reconforge.guard_webauthn_credential_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id<>OLD.tenant_id OR NEW.credential_id<>OLD.credential_id OR NEW.user_id<>OLD.user_id
       OR NEW.public_key<>OLD.public_key OR NEW.transports<>OLD.transports OR NEW.label<>OLD.label
       OR NEW.created_at<>OLD.created_at OR NEW.disabled_at IS DISTINCT FROM OLD.disabled_at OR NEW.version<>OLD.version+1
       OR NEW.sign_count<OLD.sign_count THEN
        RAISE EXCEPTION 'invalid WebAuthn credential mutation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS identity_webauthn_credential_guard ON reconforge.identity_webauthn_credentials;
CREATE TRIGGER identity_webauthn_credential_guard BEFORE UPDATE ON reconforge.identity_webauthn_credentials
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_webauthn_credential_update();
CREATE OR REPLACE FUNCTION reconforge.guard_webauthn_challenge_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id OR NEW.user_id<>OLD.user_id OR NEW.session_id<>OLD.session_id
       OR NEW.ceremony<>OLD.ceremony OR NEW.challenge<>OLD.challenge OR NEW.created_at<>OLD.created_at
       OR NEW.expires_at<>OLD.expires_at OR NEW.request_id<>OLD.request_id
       OR OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL THEN
        RAISE EXCEPTION 'invalid WebAuthn challenge mutation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS identity_webauthn_challenge_guard ON reconforge.identity_webauthn_challenges;
CREATE TRIGGER identity_webauthn_challenge_guard BEFORE UPDATE ON reconforge.identity_webauthn_challenges
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_webauthn_challenge_update();
CREATE OR REPLACE FUNCTION reconforge.reject_webauthn_event_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'WebAuthn events are append-only'; END; $$;
DROP TRIGGER IF EXISTS identity_webauthn_events_append_only ON reconforge.identity_webauthn_events;
CREATE TRIGGER identity_webauthn_events_append_only BEFORE UPDATE OR DELETE ON reconforge.identity_webauthn_events
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_webauthn_event_mutation();
"""
