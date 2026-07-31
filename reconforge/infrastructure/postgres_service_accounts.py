"""Tenant-scoped service accounts with hash-only rotating credentials."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from reconforge.auth.policy import permission_requires_human
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id

_PERMISSION = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_MAX_PERMISSIONS = 32
_MIN_TTL = timedelta(minutes=5)
_MAX_TTL = timedelta(days=90)
FORBIDDEN_SERVICE_PERMISSIONS = frozenset(
    {
        "roles.manage",
        "users.manage",
        "service_accounts.manage",
        "security.emergency",
        "security.policy.manage",
        "audit.read",
        "audit.verify",
        "finance_core.manage",
        "close.manage",
    }
)


class ServiceAccountError(ValueError):
    """Disclosure-safe service-account lifecycle failure."""


@dataclass(frozen=True)
class ServiceAccount:
    tenant_id: str
    id: str
    name: str
    display_name: str
    enabled: bool
    permissions: frozenset[str]
    version: int
    max_credential_ttl_seconds: int


@dataclass(frozen=True)
class IssuedServiceCredential:
    id: str
    service_account_id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class ServicePrincipal:
    tenant_id: str
    service_account_id: str
    name: str
    display_name: str
    credential_id: str
    permissions: frozenset[str]
    created_at: datetime


def _scope(value: str, field: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field)
    except PostgresConfigurationError as exc:
        raise ServiceAccountError(f"{field} is invalid.") from exc


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise ServiceAccountError("tenant_id is invalid.") from exc


def _permissions(values: frozenset[str] | set[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip().casefold() for value in values}))
    if not normalized or len(normalized) > _MAX_PERMISSIONS:
        raise ServiceAccountError("Service accounts require between one and 32 explicit permissions.")
    if any(not _PERMISSION.fullmatch(value) for value in normalized):
        raise ServiceAccountError("Service-account permission is invalid.")
    if FORBIDDEN_SERVICE_PERMISSIONS.intersection(normalized) or any(
        permission_requires_human(permission) for permission in normalized
    ):
        raise ServiceAccountError("Service accounts cannot receive human-only security permissions.")
    return normalized


def _display(value: str) -> str:
    normalized = " ".join(str(value).strip().split())
    if not 1 <= len(normalized) <= 160 or any(ord(character) < 32 for character in normalized):
        raise ServiceAccountError("display_name is invalid.")
    return normalized


def _token_hash(token: str) -> str:
    if not 32 <= len(token) <= 512:
        raise ServiceAccountError("Service credential is invalid.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _value(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError):
        return row[index]


class PostgresServiceAccountRepository:
    """Persist least-privilege machine identities and one-time credentials."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create_account(
        self,
        *,
        tenant_id: str,
        account_id: str,
        name: str,
        display_name: str,
        permissions: frozenset[str] | set[str] | tuple[str, ...],
        actor_id: str,
        max_credential_ttl: timedelta = timedelta(days=30),
    ) -> ServiceAccount:
        tenant = _tenant(tenant_id)
        identifier = _scope(account_id, "account_id")
        if not identifier.startswith("svc-"):
            raise ServiceAccountError("Service-account IDs must start with svc-.")
        normalized_name = _scope(name, "name")
        actor = _scope(actor_id, "actor_id")
        grants = _permissions(permissions)
        if max_credential_ttl < _MIN_TTL or max_credential_ttl > _MAX_TTL:
            raise ServiceAccountError("Maximum credential lifetime must be between five minutes and 90 days.")
        existing = self.connection.execute(
            "SELECT 1 FROM reconforge.service_accounts WHERE tenant_id=%s AND (id=%s OR name=%s)",
            (tenant, identifier, normalized_name),
        ).fetchone()
        if existing is not None:
            raise ServiceAccountError("Service account already exists.")
        known = self.connection.execute(
            "SELECT name FROM reconforge.identity_permissions WHERE tenant_id=%s AND name=ANY(%s) ORDER BY name",
            (tenant, list(grants)),
        ).fetchall()
        if tuple(str(_value(row, "name", 0)) for row in known) != grants:
            raise ServiceAccountError("Every service-account permission must already exist in the tenant registry.")
        ttl_seconds = int(max_credential_ttl.total_seconds())
        self.connection.execute(
            """INSERT INTO reconforge.service_accounts
               (tenant_id,id,name,display_name,enabled,version,max_credential_ttl_seconds,created_by)
               VALUES (%s,%s,%s,%s,TRUE,1,%s,%s)""",
            (tenant, identifier, normalized_name, _display(display_name), ttl_seconds, actor),
        )
        for permission in grants:
            self.connection.execute(
                """INSERT INTO reconforge.service_account_permissions
                   (tenant_id,service_account_id,permission_name,granted_by)
                   VALUES (%s,%s,%s,%s)""",
                (tenant, identifier, permission, actor),
            )
        self._audit(tenant, identifier, actor, "CREATE", "ALLOWED")
        return ServiceAccount(
            tenant, identifier, normalized_name, _display(display_name), True, frozenset(grants), 1, ttl_seconds
        )

    def get_account(self, *, tenant_id: str, account_id: str) -> ServiceAccount:
        tenant = _tenant(tenant_id)
        identifier = _scope(account_id, "account_id")
        row = self.connection.execute(
            """SELECT tenant_id,id,name,display_name,enabled,version,max_credential_ttl_seconds
               FROM reconforge.service_accounts WHERE tenant_id=%s AND id=%s""",
            (tenant, identifier),
        ).fetchone()
        if row is None:
            raise ServiceAccountError("Service account was not found.")
        grants = self.connection.execute(
            """SELECT permission_name FROM reconforge.service_account_permissions
               WHERE tenant_id=%s AND service_account_id=%s ORDER BY permission_name""",
            (tenant, identifier),
        ).fetchall()
        return ServiceAccount(
            str(_value(row, "tenant_id", 0)),
            str(_value(row, "id", 1)),
            str(_value(row, "name", 2)),
            str(_value(row, "display_name", 3)),
            bool(_value(row, "enabled", 4)),
            frozenset(str(_value(grant, "permission_name", 0)) for grant in grants),
            int(_value(row, "version", 5)),
            int(_value(row, "max_credential_ttl_seconds", 6)),
        )

    def replace_permissions(
        self,
        *,
        tenant_id: str,
        account_id: str,
        permissions: frozenset[str] | set[str] | tuple[str, ...],
        expected_version: int,
        actor_id: str,
    ) -> ServiceAccount:
        tenant = _tenant(tenant_id)
        identifier = _scope(account_id, "account_id")
        actor = _scope(actor_id, "actor_id")
        grants = _permissions(permissions)
        known = self.connection.execute(
            "SELECT name FROM reconforge.identity_permissions WHERE tenant_id=%s AND name=ANY(%s) ORDER BY name",
            (tenant, list(grants)),
        ).fetchall()
        if tuple(str(_value(row, "name", 0)) for row in known) != grants:
            raise ServiceAccountError("Every service-account permission must already exist in the tenant registry.")
        row = self.connection.execute(
            """UPDATE reconforge.service_accounts SET version=version+1,updated_at=now()
               WHERE tenant_id=%s AND id=%s AND enabled AND version=%s RETURNING id""",
            (tenant, identifier, expected_version),
        ).fetchone()
        if row is None:
            raise ServiceAccountError("Service-account version does not match or the account is disabled.")
        self.connection.execute(
            "DELETE FROM reconforge.service_account_permissions WHERE tenant_id=%s AND service_account_id=%s",
            (tenant, identifier),
        )
        for permission in grants:
            self.connection.execute(
                """INSERT INTO reconforge.service_account_permissions
                   (tenant_id,service_account_id,permission_name,granted_by)
                   VALUES (%s,%s,%s,%s)""",
                (tenant, identifier, permission, actor),
            )
        self._audit(tenant, identifier, actor, "REPLACE_PERMISSIONS", "ALLOWED")
        return self.get_account(tenant_id=tenant, account_id=identifier)

    def set_enabled(
        self, *, tenant_id: str, account_id: str, enabled: bool, expected_version: int, actor_id: str
    ) -> ServiceAccount:
        tenant = _tenant(tenant_id)
        identifier = _scope(account_id, "account_id")
        actor = _scope(actor_id, "actor_id")
        row = self.connection.execute(
            """UPDATE reconforge.service_accounts SET enabled=%s,version=version+1,updated_at=now()
               WHERE tenant_id=%s AND id=%s AND version=%s RETURNING id""",
            (enabled, tenant, identifier, expected_version),
        ).fetchone()
        if row is None:
            raise ServiceAccountError("Service-account version does not match.")
        if not enabled:
            self.connection.execute(
                """UPDATE reconforge.service_account_credentials SET revoked_at=now(),revoked_by=%s
                   WHERE tenant_id=%s AND service_account_id=%s AND revoked_at IS NULL""",
                (actor, tenant, identifier),
            )
        self._audit(tenant, identifier, actor, "ENABLE" if enabled else "DISABLE", "ALLOWED")
        return self.get_account(tenant_id=tenant, account_id=identifier)

    def issue_credential(
        self,
        *,
        tenant_id: str,
        account_id: str,
        actor_id: str,
        ttl: timedelta,
        rotated_from_id: str | None = None,
    ) -> IssuedServiceCredential:
        tenant = _tenant(tenant_id)
        identifier = _scope(account_id, "account_id")
        actor = _scope(actor_id, "actor_id")
        account = self.get_account(tenant_id=tenant, account_id=identifier)
        if not account.enabled or ttl < _MIN_TTL or ttl.total_seconds() > account.max_credential_ttl_seconds:
            raise ServiceAccountError("Credential lifetime is invalid or the service account is disabled.")
        rotated = _scope(rotated_from_id, "rotated_from_id") if rotated_from_id is not None else None
        if rotated is not None:
            source = self.connection.execute(
                """SELECT service_account_id,revoked_at FROM reconforge.service_account_credentials
                   WHERE tenant_id=%s AND id=%s FOR UPDATE""",
                (tenant, rotated),
            ).fetchone()
            if (
                source is None
                or str(_value(source, "service_account_id", 0)) != identifier
                or _value(source, "revoked_at", 1) is not None
            ):
                raise ServiceAccountError("Credential rotation source is invalid.")
        raw_token = "rfa_" + secrets.token_urlsafe(48)
        credential_id = f"sac-{secrets.token_hex(16)}"
        now = datetime.now(UTC).replace(microsecond=0)
        expires = now + ttl
        self.connection.execute(
            """INSERT INTO reconforge.service_account_credentials
               (tenant_id,id,service_account_id,token_hash,created_by,created_at,expires_at,rotated_from_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (tenant, credential_id, identifier, _token_hash(raw_token), actor, now, expires, rotated),
        )
        if rotated is not None:
            self.connection.execute(
                """UPDATE reconforge.service_account_credentials SET revoked_at=now(),revoked_by=%s
                   WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL""",
                (actor, tenant, rotated),
            )
        self._audit(tenant, identifier, actor, "ROTATE_CREDENTIAL" if rotated else "ISSUE_CREDENTIAL", "ALLOWED")
        return IssuedServiceCredential(credential_id, identifier, raw_token, expires)

    def authenticate(self, *, tenant_id: str, token: str) -> ServicePrincipal | None:
        tenant = _tenant(tenant_id)
        try:
            digest = _token_hash(token)
        except ServiceAccountError:
            return None
        row = self.connection.execute(
            """UPDATE reconforge.service_account_credentials credentials
               SET last_used_at=CASE WHEN last_used_at IS NULL OR last_used_at < now()-interval '5 minutes'
                                     THEN now() ELSE last_used_at END
               FROM reconforge.service_accounts accounts
               WHERE credentials.tenant_id=%s AND credentials.token_hash=%s
                 AND accounts.tenant_id=credentials.tenant_id AND accounts.id=credentials.service_account_id
                 AND accounts.enabled AND credentials.revoked_at IS NULL AND credentials.expires_at>now()
               RETURNING accounts.id AS service_account_id,accounts.name,accounts.display_name,
                         credentials.id AS credential_id,accounts.created_at""",
            (tenant, digest),
        ).fetchone()
        if row is None:
            return None
        account_id = str(_value(row, "service_account_id", 0))
        grants = self.connection.execute(
            """SELECT permission_name FROM reconforge.service_account_permissions
               WHERE tenant_id=%s AND service_account_id=%s ORDER BY permission_name""",
            (tenant, account_id),
        ).fetchall()
        return ServicePrincipal(
            tenant,
            account_id,
            str(_value(row, "name", 1)),
            str(_value(row, "display_name", 2)),
            str(_value(row, "credential_id", 3)),
            frozenset(str(_value(grant, "permission_name", 0)) for grant in grants),
            _value(row, "created_at", 4),
        )

    def revoke_token(self, *, tenant_id: str, token: str, actor_id: str) -> bool:
        tenant = _tenant(tenant_id)
        actor = _scope(actor_id, "actor_id")
        try:
            digest = _token_hash(token)
        except ServiceAccountError:
            return False
        row = self.connection.execute(
            """UPDATE reconforge.service_account_credentials SET revoked_at=now(),revoked_by=%s
               WHERE tenant_id=%s AND token_hash=%s AND revoked_at IS NULL
               RETURNING service_account_id""",
            (actor, tenant, digest),
        ).fetchone()
        if row is None:
            return False
        self._audit(tenant, str(_value(row, "service_account_id", 0)), actor, "REVOKE_CREDENTIAL", "ALLOWED")
        return True

    def revoke_credential(self, *, tenant_id: str, credential_id: str, actor_id: str) -> bool:
        tenant = _tenant(tenant_id)
        identifier = _scope(credential_id, "credential_id")
        actor = _scope(actor_id, "actor_id")
        row = self.connection.execute(
            """UPDATE reconforge.service_account_credentials SET revoked_at=now(),revoked_by=%s
               WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL RETURNING service_account_id""",
            (actor, tenant, identifier),
        ).fetchone()
        if row is None:
            return False
        self._audit(tenant, str(_value(row, "service_account_id", 0)), actor, "REVOKE_CREDENTIAL", "ALLOWED")
        return True

    def _audit(self, tenant: str, account_id: str, actor: str, action: str, outcome: str) -> None:
        self.connection.execute(
            """INSERT INTO reconforge.service_account_events
               (tenant_id,id,service_account_id,actor_id,action,outcome)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (tenant, f"sae-{secrets.token_hex(16)}", account_id, actor, action, outcome),
        )


POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.service_accounts (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL CHECK (id ~ '^svc-[a-z0-9][a-z0-9_-]{0,59}$'),
    name TEXT NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 160),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    max_credential_ttl_seconds INTEGER NOT NULL CHECK (max_credential_ttl_seconds BETWEEN 300 AND 7776000),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,name)
);

CREATE TABLE IF NOT EXISTS reconforge.service_account_permissions (
    tenant_id TEXT NOT NULL,
    service_account_id TEXT NOT NULL,
    permission_name TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT service_account_permissions_human_only CHECK (
      permission_name NOT IN ('roles.manage','users.manage','service_accounts.manage','security.emergency',
        'security.policy.manage','security.center.read','audit.read','audit.verify','finance_core.manage','close.manage')
    ),
    CHECK (permission_name !~ '\\.(approve|review|complete)$'),
    PRIMARY KEY (tenant_id,service_account_id,permission_name),
    FOREIGN KEY (tenant_id,service_account_id) REFERENCES reconforge.service_accounts(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,permission_name) REFERENCES reconforge.identity_permissions(tenant_id,name) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.service_account_credentials (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^sac-[0-9a-f]{32}$'),
    service_account_id TEXT NOT NULL,
    token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    rotated_from_id TEXT,
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,token_hash),
    FOREIGN KEY (tenant_id,service_account_id) REFERENCES reconforge.service_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,rotated_from_id) REFERENCES reconforge.service_account_credentials(tenant_id,id) ON DELETE RESTRICT,
    CHECK (expires_at > created_at),
    CHECK ((revoked_at IS NULL AND revoked_by IS NULL) OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS reconforge.service_account_events (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^sae-[0-9a-f]{32}$'),
    service_account_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('CREATE','REPLACE_PERMISSIONS','ENABLE','DISABLE','ISSUE_CREDENTIAL','ROTATE_CREDENTIAL','REVOKE_CREDENTIAL')),
    outcome TEXT NOT NULL CHECK (outcome IN ('ALLOWED','DENIED')),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,service_account_id) REFERENCES reconforge.service_accounts(tenant_id,id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_service_account_credentials_active
    ON reconforge.service_account_credentials(tenant_id,token_hash,expires_at,revoked_at);

CREATE OR REPLACE FUNCTION reconforge.guard_service_account_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id OR NEW.name<>OLD.name
       OR NEW.max_credential_ttl_seconds<>OLD.max_credential_ttl_seconds
       OR NEW.created_by<>OLD.created_by OR NEW.created_at<>OLD.created_at
       OR NEW.version<>OLD.version+1 THEN
        RAISE EXCEPTION 'service account immutable fields or version transition violated' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;

DROP TRIGGER IF EXISTS trg_service_account_update ON reconforge.service_accounts;
CREATE TRIGGER trg_service_account_update
BEFORE UPDATE ON reconforge.service_accounts
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_service_account_update();

CREATE OR REPLACE FUNCTION reconforge.guard_service_account_permission()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
DECLARE permission_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id || '-service-account-' || NEW.service_account_id, 0));
    SELECT count(*) INTO permission_count
      FROM reconforge.service_account_permissions
     WHERE tenant_id=NEW.tenant_id AND service_account_id=NEW.service_account_id
       AND (TG_OP <> 'UPDATE' OR permission_name <> OLD.permission_name);
    IF permission_count >= 32 THEN
        RAISE EXCEPTION 'service account permission ceiling exceeded' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;

DROP TRIGGER IF EXISTS trg_service_account_permission_guard ON reconforge.service_account_permissions;
CREATE TRIGGER trg_service_account_permission_guard
BEFORE INSERT OR UPDATE ON reconforge.service_account_permissions
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_service_account_permission();

CREATE OR REPLACE FUNCTION reconforge.guard_service_account_credential()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
DECLARE account_enabled BOOLEAN;
DECLARE account_max_ttl INTEGER;
DECLARE rotated_account TEXT;
DECLARE rotated_revoked TIMESTAMPTZ;
BEGIN
    SELECT enabled,max_credential_ttl_seconds INTO account_enabled,account_max_ttl
      FROM reconforge.service_accounts
     WHERE tenant_id=NEW.tenant_id AND id=NEW.service_account_id FOR UPDATE;
    IF account_enabled IS DISTINCT FROM TRUE OR NEW.expires_at > NEW.created_at + make_interval(secs=>account_max_ttl) THEN
        RAISE EXCEPTION 'service account credential policy violation' USING ERRCODE='check_violation';
    END IF;
    IF NEW.rotated_from_id IS NOT NULL THEN
        SELECT service_account_id,revoked_at INTO rotated_account,rotated_revoked
          FROM reconforge.service_account_credentials
         WHERE tenant_id=NEW.tenant_id AND id=NEW.rotated_from_id FOR UPDATE;
        IF rotated_account IS DISTINCT FROM NEW.service_account_id OR rotated_revoked IS NOT NULL THEN
            RAISE EXCEPTION 'service account rotation source violation' USING ERRCODE='check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$reconforge$;

DROP TRIGGER IF EXISTS trg_service_account_credential_guard ON reconforge.service_account_credentials;
CREATE TRIGGER trg_service_account_credential_guard
BEFORE INSERT ON reconforge.service_account_credentials
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_service_account_credential();

CREATE OR REPLACE FUNCTION reconforge.guard_service_account_credential_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id OR NEW.service_account_id<>OLD.service_account_id
       OR NEW.token_hash<>OLD.token_hash OR NEW.created_by<>OLD.created_by OR NEW.created_at<>OLD.created_at
       OR NEW.expires_at<>OLD.expires_at OR NEW.rotated_from_id IS DISTINCT FROM OLD.rotated_from_id THEN
        RAISE EXCEPTION 'immutable service credential fields cannot change' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;

DROP TRIGGER IF EXISTS trg_service_account_credential_update ON reconforge.service_account_credentials;
CREATE TRIGGER trg_service_account_credential_update
BEFORE UPDATE ON reconforge.service_account_credentials
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_service_account_credential_update();

CREATE OR REPLACE FUNCTION reconforge.reject_service_account_event_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    RAISE EXCEPTION 'service account events are append-only' USING ERRCODE='check_violation';
END
$reconforge$;

DROP TRIGGER IF EXISTS trg_service_account_events_append_only ON reconforge.service_account_events;
CREATE TRIGGER trg_service_account_events_append_only
BEFORE UPDATE OR DELETE ON reconforge.service_account_events
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_service_account_event_mutation();

ALTER TABLE reconforge.service_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_account_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_account_permissions FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_account_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_account_credentials FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_account_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.service_account_events FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'service_accounts','service_account_permissions','service_account_credentials','service_account_events'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope'
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
