"""Hash-only, tenant-scoped SCIM client credential lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from reconforge.auth.scim import SCIMError
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id

POSTGRES_SCIM_AUTH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.scim_credentials (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL CHECK (id ~ '^scc-[0-9a-f]{32}$'),
    provisioning_domain TEXT NOT NULL CHECK (provisioning_domain ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    client_id TEXT NOT NULL CHECK (client_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_by TEXT NOT NULL CHECK (created_by ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    rotated_from_id TEXT,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, token_hash),
    UNIQUE (tenant_id, provisioning_domain, client_id, id),
    FOREIGN KEY (tenant_id, rotated_from_id)
        REFERENCES reconforge.scim_credentials(tenant_id, id) ON DELETE RESTRICT,
    CHECK (expires_at > created_at),
    CHECK ((revoked_at IS NULL AND revoked_by IS NULL) OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_scim_credentials_token
    ON reconforge.scim_credentials (tenant_id, token_hash, expires_at, revoked_at);

ALTER TABLE reconforge.scim_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_credentials FORCE ROW LEVEL SECURITY;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname='reconforge' AND tablename='scim_credentials' AND policyname='tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.scim_credentials
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END
$reconforge$;
"""


@dataclass(frozen=True)
class SCIMClientPrincipal:
    tenant_id: str
    provisioning_domain: str
    client_id: str
    credential_id: str


@dataclass(frozen=True)
class IssuedSCIMCredential:
    id: str
    token: str
    tenant_id: str
    provisioning_domain: str
    client_id: str
    expires_at: datetime


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise SCIMError("SCIM credential scope is invalid.") from exc


def _scope(value: str, field: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field)
    except PostgresConfigurationError as exc:
        raise SCIMError(f"{field} is invalid.") from exc


def _hash(token: str) -> str:
    if len(token) < 32 or len(token) > 512:
        raise SCIMError("SCIM bearer credential is invalid.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PostgresSCIMCredentialRepository:
    """Create, authenticate, rotate, and revoke opaque SCIM credentials."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def issue(
        self,
        *,
        tenant_id: str,
        provisioning_domain: str,
        client_id: str,
        actor_id: str,
        ttl: timedelta,
        rotated_from_id: str | None = None,
    ) -> IssuedSCIMCredential:
        tenant = _tenant(tenant_id)
        domain = _scope(provisioning_domain, "provisioning_domain")
        client = _scope(client_id, "client_id")
        actor = _scope(actor_id, "actor_id")
        if ttl < timedelta(minutes=5) or ttl > timedelta(days=366):
            raise SCIMError("SCIM credential lifetime must be between five minutes and 366 days.")
        rotated_from = _scope(rotated_from_id, "rotated_from_id") if rotated_from_id is not None else None
        if rotated_from is not None:
            row = self.connection.execute(
                """SELECT provisioning_domain, client_id, revoked_at
                   FROM reconforge.scim_credentials
                   WHERE tenant_id=%s AND id=%s FOR UPDATE""",
                (tenant, rotated_from),
            ).fetchone()
            if row is None or str(row[0]) != domain or str(row[1]) != client or row[2] is not None:
                raise SCIMError("SCIM credential rotation source is invalid.")
        raw_token = "rfs_" + secrets.token_urlsafe(48)
        credential_id = f"scc-{secrets.token_hex(16)}"
        now = datetime.now(UTC).replace(microsecond=0)
        expires_at = now + ttl
        self.connection.execute(
            """INSERT INTO reconforge.scim_credentials
               (tenant_id,id,provisioning_domain,client_id,token_hash,created_by,created_at,expires_at,rotated_from_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (tenant, credential_id, domain, client, _hash(raw_token), actor, now, expires_at, rotated_from),
        )
        if rotated_from is not None:
            self.connection.execute(
                """UPDATE reconforge.scim_credentials SET revoked_at=now(), revoked_by=%s
                   WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL""",
                (actor, tenant, rotated_from),
            )
        return IssuedSCIMCredential(credential_id, raw_token, tenant, domain, client, expires_at)

    def authenticate(self, *, tenant_id: str, token: str) -> SCIMClientPrincipal | None:
        tenant = _tenant(tenant_id)
        try:
            digest = _hash(token)
        except SCIMError:
            return None
        row = self.connection.execute(
            """UPDATE reconforge.scim_credentials
               SET last_used_at=CASE
                   WHEN last_used_at IS NULL OR last_used_at < now() - interval '5 minutes' THEN now()
                   ELSE last_used_at END
               WHERE tenant_id=%s AND token_hash=%s AND revoked_at IS NULL AND expires_at > now()
               RETURNING provisioning_domain, client_id, id""",
            (tenant, digest),
        ).fetchone()
        if row is None:
            return None
        return SCIMClientPrincipal(tenant, str(row[0]), str(row[1]), str(row[2]))

    def revoke(self, *, tenant_id: str, credential_id: str, actor_id: str) -> bool:
        tenant = _tenant(tenant_id)
        identifier = _scope(credential_id, "credential_id")
        actor = _scope(actor_id, "actor_id")
        row = self.connection.execute(
            """UPDATE reconforge.scim_credentials SET revoked_at=now(), revoked_by=%s
               WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL RETURNING id""",
            (actor, tenant, identifier),
        ).fetchone()
        return row is not None
