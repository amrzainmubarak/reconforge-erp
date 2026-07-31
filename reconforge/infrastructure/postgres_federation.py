"""Tenant-scoped durable federation replay, identity links, and session binding."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from reconforge.auth.federation import FederatedPrincipal
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.infrastructure.postgres_identity import (
    PostgresIdentityError,
    PostgresIdentityRepository,
    PostgresSession,
)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

POSTGRES_FEDERATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.federation_login_challenges (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL CHECK (provider_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
    protocol TEXT NOT NULL CHECK (protocol IN ('oidc', 'saml')),
    challenge_hash TEXT NOT NULL CHECK (challenge_hash ~ '^[0-9a-f]{64}$'),
    correlation_hash TEXT NOT NULL CHECK (correlation_hash ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provider_id, challenge_hash)
);

CREATE TABLE IF NOT EXISTS reconforge.federation_assertion_replays (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL CHECK (provider_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
    assertion_hash TEXT NOT NULL CHECK (assertion_hash ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provider_id, assertion_hash)
);

CREATE TABLE IF NOT EXISTS reconforge.federation_identity_links (
    tenant_id TEXT NOT NULL,
    provider_id TEXT NOT NULL CHECK (provider_id ~ '^[a-z][a-z0-9_-]{0,63}$'),
    external_subject_hash TEXT NOT NULL CHECK (external_subject_hash ~ '^[0-9a-f]{64}$'),
    user_id TEXT NOT NULL,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    linked_by TEXT NOT NULL,
    disabled_at TIMESTAMPTZ,
    disabled_by TEXT,
    PRIMARY KEY (tenant_id, provider_id, external_subject_hash),
    UNIQUE (tenant_id, provider_id, user_id),
    FOREIGN KEY (tenant_id, user_id)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT,
    CHECK ((disabled_at IS NULL AND disabled_by IS NULL) OR (disabled_at IS NOT NULL AND disabled_by IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS reconforge.federation_identity_events (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    user_id TEXT,
    action TEXT NOT NULL CHECK (action IN ('LINKED', 'DISABLED', 'AUTHENTICATED', 'LOGOUT', 'FEDERATION_AUTHENTICATE')),
    outcome TEXT NOT NULL DEFAULT 'ALLOWED' CHECK (outcome IN ('ALLOWED', 'DENIED')),
    reason_code TEXT,
    actor_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

ALTER TABLE reconforge.federation_assertion_replays ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_assertion_replays FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_identity_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_identity_links FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_identity_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_identity_events FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_login_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.federation_login_challenges FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS federation_login_challenges_tenant ON reconforge.federation_login_challenges;
CREATE POLICY federation_login_challenges_tenant ON reconforge.federation_login_challenges
USING (tenant_id = current_setting('app.tenant_id', true))
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS federation_assertion_replays_tenant ON reconforge.federation_assertion_replays;
CREATE POLICY federation_assertion_replays_tenant ON reconforge.federation_assertion_replays
USING (tenant_id = current_setting('app.tenant_id', true))
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS federation_identity_links_tenant ON reconforge.federation_identity_links;
CREATE POLICY federation_identity_links_tenant ON reconforge.federation_identity_links
USING (tenant_id = current_setting('app.tenant_id', true))
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS federation_identity_events_tenant ON reconforge.federation_identity_events;
CREATE POLICY federation_identity_events_tenant ON reconforge.federation_identity_events
USING (tenant_id = current_setting('app.tenant_id', true))
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresFederationError(RuntimeError):
    """Safe persistent federation failure."""


@dataclass(frozen=True)
class FederationLoginChallenge:
    challenge_id: str
    correlation: str
    protocol: str
    expires_at: str


@dataclass(frozen=True)
class PostgresFederationAuditSink:
    """Persist sanitized federation policy outcomes inside one tenant boundary."""

    connection: Any
    tenant_id: str

    def record(self, *, action: str, provider_id: str, outcome: str, reason_code: str | None) -> None:
        if action != "federation_authenticate" or outcome not in {"allowed", "denied"}:
            raise PostgresFederationError("Federation audit event is invalid.")
        tenant = _tenant(self.tenant_id)
        provider = _scope(provider_id, "provider_id")
        reason = None if reason_code is None else _scope(reason_code, "reason_code")
        self.connection.execute(
            """
            INSERT INTO reconforge.federation_identity_events
                (tenant_id, id, provider_id, action, outcome, reason_code, actor_id)
            VALUES (%s, %s, %s, 'FEDERATION_AUTHENTICATE', %s, %s, 'federation-system')
            """,
            (tenant, f"fie-{secrets.token_hex(16)}", provider, outcome.upper(), reason),
        )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresFederationError("Federation tenant identifier is invalid.") from exc


def _scope(value: str, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresFederationError(f"Federation {field_name} is invalid.") from exc
    if not _ID_PATTERN.fullmatch(normalized):
        raise PostgresFederationError(f"Federation {field_name} is invalid.")
    return normalized


def _subject_hash(principal: FederatedPrincipal) -> str:
    return _hash(f"{principal.issuer}\x00{principal.subject}")


@dataclass(frozen=True)
class PostgresFederationReplayStore:
    connection: Any
    tenant_id: str

    def consume_once(self, *, provider_id: str, assertion_id: str, expires_at: datetime) -> bool:
        tenant = _tenant(self.tenant_id)
        provider = _scope(provider_id, "provider_id")
        if expires_at.tzinfo is None:
            raise PostgresFederationError("Federation assertion expiry must include a timezone.")
        row = self.connection.execute(
            """
            INSERT INTO reconforge.federation_assertion_replays
                (tenant_id, provider_id, assertion_hash, expires_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING assertion_hash
            """,
            (tenant, provider, _hash(assertion_id), expires_at),
        ).fetchone()
        return row is not None


@dataclass(frozen=True)
class PostgresFederationRepository:
    connection: Any

    def issue_challenge(self, *, tenant_id: str, provider_id: str, protocol: str) -> FederationLoginChallenge:
        tenant = _tenant(tenant_id)
        provider = _scope(provider_id, "provider_id")
        if protocol not in {"oidc", "saml"}:
            raise PostgresFederationError("Federation challenge protocol is invalid.")
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"federation-challenge:{tenant}:{provider}",),
        )
        self.connection.execute(
            """
            DELETE FROM reconforge.federation_login_challenges
            WHERE tenant_id = %s AND provider_id = %s
              AND (expires_at <= now() OR consumed_at IS NOT NULL)
            """,
            (tenant, provider),
        )
        active = self.connection.execute(
            """
            SELECT count(*) FROM reconforge.federation_login_challenges
            WHERE tenant_id = %s AND provider_id = %s
              AND consumed_at IS NULL AND expires_at > now()
            """,
            (tenant, provider),
        ).fetchone()
        if active is None or int(active[0]) >= 100:
            raise PostgresFederationError("Federation challenge capacity is unavailable.")
        challenge_id = secrets.token_urlsafe(32)
        correlation = secrets.token_urlsafe(32) if protocol == "oidc" else f"_{secrets.token_hex(24)}"
        expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=5)
        row = self.connection.execute(
            """
            INSERT INTO reconforge.federation_login_challenges
                (tenant_id, provider_id, protocol, challenge_hash, correlation_hash, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING expires_at
            """,
            (tenant, provider, protocol, _hash(challenge_id), _hash(correlation), expires_at),
        ).fetchone()
        if row is None:
            raise PostgresFederationError("Federation challenge could not be created.")
        returned_expiry = row[0]
        expiry_text = returned_expiry.isoformat() if isinstance(returned_expiry, datetime) else str(returned_expiry)
        return FederationLoginChallenge(challenge_id, correlation, protocol, expiry_text)

    def consume_challenge(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        protocol: str,
        challenge_id: str,
        correlation: str,
    ) -> bool:
        tenant = _tenant(tenant_id)
        provider = _scope(provider_id, "provider_id")
        if protocol not in {"oidc", "saml"} or not challenge_id or not correlation:
            raise PostgresFederationError("Federation challenge is invalid.")
        row = self.connection.execute(
            """
            UPDATE reconforge.federation_login_challenges
            SET consumed_at = now()
            WHERE tenant_id = %s AND provider_id = %s AND protocol = %s
              AND challenge_hash = %s AND correlation_hash = %s
              AND consumed_at IS NULL AND expires_at > now()
            RETURNING challenge_hash
            """,
            (tenant, provider, protocol, _hash(challenge_id), _hash(correlation)),
        ).fetchone()
        return row is not None

    def link_identity(
        self,
        *,
        tenant_id: str,
        principal: FederatedPrincipal,
        user_id: str,
        actor_id: str,
    ) -> None:
        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        actor = _scope(actor_id, "actor_id")
        provider = _scope(principal.provider_id, "provider_id")
        subject_hash = _subject_hash(principal)
        row = self.connection.execute(
            """
            INSERT INTO reconforge.federation_identity_links
                (tenant_id, provider_id, external_subject_hash, user_id, linked_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, provider_id, external_subject_hash) DO UPDATE
            SET user_id = reconforge.federation_identity_links.user_id
            RETURNING user_id, disabled_at
            """,
            (tenant, provider, subject_hash, user, actor),
        ).fetchone()
        if row is None or str(row[0]) != user or row[1] is not None:
            raise PostgresFederationError("Federated identity link conflicts with existing state.")
        self._event(tenant, provider, user, "LINKED", actor)

    def complete_login(self, *, tenant_id: str, principal: FederatedPrincipal) -> PostgresSession:
        tenant = _tenant(tenant_id)
        provider = _scope(principal.provider_id, "provider_id")
        row = self.connection.execute(
            """
            SELECT links.user_id, users.disabled
            FROM reconforge.federation_identity_links links
            JOIN reconforge.identity_users users
              ON users.tenant_id = links.tenant_id AND users.id = links.user_id
            WHERE links.tenant_id = %s AND links.provider_id = %s
              AND links.external_subject_hash = %s AND links.disabled_at IS NULL
            FOR UPDATE OF links, users
            """,
            (tenant, provider, _subject_hash(principal)),
        ).fetchone()
        if row is None or bool(row[1]):
            raise PostgresFederationError("Federated identity is not linked to an active local user.")
        user_id = str(row[0])
        identity = PostgresIdentityRepository(self.connection)
        local_roles = frozenset(identity.user_roles(tenant_id=tenant, user_id=user_id))
        if not principal.roles or not set(principal.roles).issubset(local_roles):
            raise PostgresFederationError("Federated roles exceed the local user role assignment.")
        try:
            session = identity.create_session(tenant_id=tenant, user_id=user_id)
        except PostgresIdentityError as exc:
            raise PostgresFederationError("Federated session could not be created.") from exc
        self._event(tenant, provider, user_id, "AUTHENTICATED", user_id)
        return session

    def disable_link(self, *, tenant_id: str, provider_id: str, user_id: str, actor_id: str) -> bool:
        tenant = _tenant(tenant_id)
        provider = _scope(provider_id, "provider_id")
        user = _scope(user_id, "user_id")
        actor = _scope(actor_id, "actor_id")
        row = self.connection.execute(
            """
            UPDATE reconforge.federation_identity_links
            SET disabled_at = now(), disabled_by = %s
            WHERE tenant_id = %s AND provider_id = %s AND user_id = %s AND disabled_at IS NULL
            RETURNING user_id
            """,
            (actor, tenant, provider, user),
        ).fetchone()
        if row is None:
            return False
        self._event(tenant, provider, user, "DISABLED", actor)
        return True

    def _event(self, tenant_id: str, provider_id: str, user_id: str, action: str, actor_id: str) -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.federation_identity_events
                (tenant_id, id, provider_id, user_id, action, outcome, actor_id)
            VALUES (%s, %s, %s, %s, %s, 'ALLOWED', %s)
            """,
            (tenant_id, f"fie-{secrets.token_hex(16)}", provider_id, user_id, action, actor_id),
        )
