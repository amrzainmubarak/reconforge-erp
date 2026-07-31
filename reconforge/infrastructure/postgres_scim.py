"""Forced-RLS PostgreSQL persistence for tenant-scoped SCIM resources."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from reconforge.auth.passwords import hash_password
from reconforge.auth.scim import SCIMError, SCIMGroup, SCIMGroupWrite, SCIMUser, SCIMUserWrite
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id

_USER_GET_SQL = """SELECT id, provisioning_domain, external_id, username, display_name,
                           email, active, version, created_at, updated_at
                    FROM reconforge.scim_users
                    WHERE tenant_id=%s AND provisioning_domain=%s AND id=%s"""
_USER_GET_FOR_UPDATE_SQL = _USER_GET_SQL + " FOR UPDATE"  # static module composition; no input is interpolated
_USER_LIST_SQL = """SELECT id, provisioning_domain, external_id, username, display_name,
                            email, active, version, created_at, updated_at
                     FROM reconforge.scim_users
                     WHERE tenant_id=%s AND provisioning_domain=%s
                     ORDER BY id LIMIT %s OFFSET %s"""
_USER_LIST_USERNAME_SQL = """SELECT id, provisioning_domain, external_id, username, display_name,
                                     email, active, version, created_at, updated_at
                              FROM reconforge.scim_users
                              WHERE tenant_id=%s AND provisioning_domain=%s AND username=%s
                              ORDER BY id LIMIT %s OFFSET %s"""
_USER_LIST_EXTERNAL_SQL = """SELECT id, provisioning_domain, external_id, username, display_name,
                                     email, active, version, created_at, updated_at
                              FROM reconforge.scim_users
                              WHERE tenant_id=%s AND provisioning_domain=%s AND external_id=%s
                              ORDER BY id LIMIT %s OFFSET %s"""
_GROUP_GET_SQL = """SELECT id, provisioning_domain, external_id, display_name, version, created_at, updated_at
                     FROM reconforge.scim_groups
                     WHERE tenant_id=%s AND provisioning_domain=%s AND id=%s"""
_GROUP_GET_FOR_UPDATE_SQL = _GROUP_GET_SQL + " FOR UPDATE"  # static module composition; no input is interpolated
_GROUP_LIST_SQL = """SELECT id, provisioning_domain, external_id, display_name, version, created_at, updated_at
                      FROM reconforge.scim_groups
                      WHERE tenant_id=%s AND provisioning_domain=%s
                      ORDER BY id LIMIT %s OFFSET %s"""
_GROUP_LIST_NAME_SQL = """SELECT id, provisioning_domain, external_id, display_name, version, created_at, updated_at
                           FROM reconforge.scim_groups
                           WHERE tenant_id=%s AND provisioning_domain=%s AND display_name=%s
                           ORDER BY id LIMIT %s OFFSET %s"""
_GROUP_LIST_EXTERNAL_SQL = """SELECT id, provisioning_domain, external_id, display_name, version, created_at, updated_at
                               FROM reconforge.scim_groups
                               WHERE tenant_id=%s AND provisioning_domain=%s AND external_id=%s
                               ORDER BY id LIMIT %s OFFSET %s"""

POSTGRES_SCIM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.scim_users (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    provisioning_domain TEXT NOT NULL CHECK (provisioning_domain ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    id TEXT NOT NULL CHECK (id ~ '^scu-[0-9a-f]{32}$'),
    external_id TEXT NOT NULL CHECK (length(external_id) BETWEEN 1 AND 255),
    user_id TEXT NOT NULL,
    username TEXT NOT NULL CHECK (length(username) BETWEEN 1 AND 160),
    display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
    email TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provisioning_domain, id),
    UNIQUE (tenant_id, provisioning_domain, external_id),
    UNIQUE (tenant_id, username),
    UNIQUE (tenant_id, user_id),
    FOREIGN KEY (tenant_id, user_id)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.scim_groups (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    provisioning_domain TEXT NOT NULL CHECK (provisioning_domain ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    id TEXT NOT NULL CHECK (id ~ '^scg-[0-9a-f]{32}$'),
    external_id TEXT NOT NULL CHECK (length(external_id) BETWEEN 1 AND 255),
    display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provisioning_domain, id),
    UNIQUE (tenant_id, provisioning_domain, external_id)
);

CREATE TABLE IF NOT EXISTS reconforge.scim_group_members (
    tenant_id TEXT NOT NULL,
    provisioning_domain TEXT NOT NULL,
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provisioning_domain, group_id, user_id),
    FOREIGN KEY (tenant_id, provisioning_domain, group_id)
        REFERENCES reconforge.scim_groups(tenant_id, provisioning_domain, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, provisioning_domain, user_id)
        REFERENCES reconforge.scim_users(tenant_id, provisioning_domain, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.scim_events (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL CHECK (id ~ '^sce-[0-9a-f]{32}$'),
    provisioning_domain TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('User', 'Group')),
    resource_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('CREATE', 'REPLACE', 'DEACTIVATE', 'DELETE', 'PROVISION')),
    outcome TEXT NOT NULL CHECK (outcome IN ('ALLOWED', 'DENIED')),
    reason_code TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS idx_scim_users_external
    ON reconforge.scim_users (tenant_id, provisioning_domain, external_id);
CREATE INDEX IF NOT EXISTS idx_scim_groups_external
    ON reconforge.scim_groups (tenant_id, provisioning_domain, external_id);
CREATE INDEX IF NOT EXISTS idx_scim_events_resource
    ON reconforge.scim_events (tenant_id, provisioning_domain, resource_type, resource_id, occurred_at);

ALTER TABLE reconforge.scim_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_users FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_groups FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_group_members FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.scim_events FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['scim_users', 'scim_groups', 'scim_group_members', 'scim_events']
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


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise SCIMError("SCIM tenant scope is invalid.") from exc


def _scope(value: str, field: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field)
    except PostgresConfigurationError as exc:
        raise SCIMError(f"{field} is invalid.") from exc


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SCIMError("Stored SCIM timestamp is invalid.") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _user(row: Any) -> SCIMUser:
    return SCIMUser(
        id=str(_value(row, "id", 0)),
        provisioning_domain=str(_value(row, "provisioning_domain", 1)),
        external_id=str(_value(row, "external_id", 2)),
        username=str(_value(row, "username", 3)),
        display_name=str(_value(row, "display_name", 4)),
        email=str(_value(row, "email", 5)) if _value(row, "email", 5) is not None else None,
        active=bool(_value(row, "active", 6)),
        version=int(_value(row, "version", 7)),
        created_at=_time(_value(row, "created_at", 8)),
        updated_at=_time(_value(row, "updated_at", 9)),
    )


class PostgresSCIMRepository:
    """Persist SCIM lifecycle and identity effects in a caller transaction."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def put_user(self, *, tenant_id: str, domain: str, resource: SCIMUserWrite) -> tuple[SCIMUser, bool]:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        self._lock_resource(tenant, provider, "User", resource.externalId)
        existing = self.connection.execute(
            """SELECT id, provisioning_domain, external_id, username, display_name,
                      email, active, version, created_at, updated_at
               FROM reconforge.scim_users
               WHERE tenant_id=%s AND provisioning_domain=%s AND external_id=%s
               FOR UPDATE""",
            (tenant, provider, resource.externalId),
        ).fetchone()
        email = next((item.value for item in resource.emails if item.primary), None)
        if email is None and resource.emails:
            email = resource.emails[0].value
        display = resource.displayName or (resource.name.formatted if resource.name else None) or resource.userName
        if existing is not None:
            current = _user(existing)
            state = (resource.userName, display, email, resource.active)
            if state == (current.username, current.display_name, current.email, current.active):
                return current, False
            row = self.connection.execute(
                """UPDATE reconforge.scim_users
                    SET username=%s, display_name=%s, email=%s, active=%s, version=version+1, updated_at=now()
                    WHERE tenant_id=%s AND provisioning_domain=%s AND id=%s
                    RETURNING id, provisioning_domain, external_id, username, display_name,
                              email, active, version, created_at, updated_at""",
                (*state, tenant, provider, current.id),
            ).fetchone()
            self.connection.execute(
                """UPDATE reconforge.identity_users
                   SET username=%s, display_name=%s, email=%s,
                       lifecycle_version=CASE WHEN disabled=%s THEN lifecycle_version ELSE lifecycle_version+1 END,
                       updated_at=CASE WHEN disabled=%s THEN updated_at ELSE now() END,
                       disabled=%s,
                       disabled_at=CASE WHEN %s THEN COALESCE(disabled_at,now()) ELSE NULL END,
                       disabled_by=CASE WHEN %s THEN COALESCE(disabled_by,%s) ELSE NULL END
                   WHERE tenant_id=%s AND id=%s""",
                (
                    resource.userName,
                    display,
                    email,
                    not resource.active,
                    not resource.active,
                    not resource.active,
                    not resource.active,
                    not resource.active,
                    f"scim:{provider}",
                    tenant,
                    current.id,
                ),
            )
            if not resource.active:
                self._revoke_sessions(tenant, current.id)
            if row is None:
                raise SCIMError("SCIM user update did not return a resource.")
            return _user(row), False

        resource_id = f"scu-{secrets.token_hex(16)}"
        inaccessible_password = hash_password(secrets.token_urlsafe(48))
        self.connection.execute(
            """INSERT INTO reconforge.identity_users
                (tenant_id, id, username, display_name, email, password_hash, password_salt,
                 password_iterations, password_algorithm, password_changed_at, disabled,
                 disabled_at, disabled_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,
                       CASE WHEN %s THEN now() ELSE NULL END,
                       CASE WHEN %s THEN %s ELSE NULL END)""",
            (
                tenant,
                resource_id,
                resource.userName,
                display,
                email,
                inaccessible_password.hash_hex,
                inaccessible_password.salt_hex,
                inaccessible_password.iterations,
                inaccessible_password.algorithm,
                not resource.active,
                not resource.active,
                not resource.active,
                f"scim:{provider}",
            ),
        )
        row = self.connection.execute(
            """INSERT INTO reconforge.scim_users
                (tenant_id, provisioning_domain, id, external_id, user_id, username, display_name, email, active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, provisioning_domain, external_id, username, display_name,
                          email, active, version, created_at, updated_at""",
            (
                tenant,
                provider,
                resource_id,
                resource.externalId,
                resource_id,
                resource.userName,
                display,
                email,
                resource.active,
            ),
        ).fetchone()
        if row is None:
            raise SCIMError("SCIM user creation did not return a resource.")
        return _user(row), True

    def set_user_active(self, *, tenant_id: str, domain: str, resource_id: str, active: bool) -> SCIMUser:
        tenant, provider, identifier = (
            _tenant(tenant_id),
            _scope(domain, "provisioning_domain"),
            _scope(resource_id, "resource_id"),
        )
        row = self.connection.execute(
            """UPDATE reconforge.scim_users
                SET active=%s, version=CASE WHEN active=%s THEN version ELSE version+1 END,
                    updated_at=CASE WHEN active=%s THEN updated_at ELSE now() END
                WHERE tenant_id=%s AND provisioning_domain=%s AND id=%s
                RETURNING id, provisioning_domain, external_id, username, display_name,
                          email, active, version, created_at, updated_at""",
            (active, active, active, tenant, provider, identifier),
        ).fetchone()
        if row is None:
            raise SCIMError("SCIM User was not found.")
        self.connection.execute(
            """UPDATE reconforge.identity_users
               SET lifecycle_version=CASE WHEN disabled=%s THEN lifecycle_version ELSE lifecycle_version+1 END,
                   updated_at=CASE WHEN disabled=%s THEN updated_at ELSE now() END,
                   disabled=%s,
                   disabled_at=CASE WHEN %s THEN COALESCE(disabled_at,now()) ELSE NULL END,
                   disabled_by=CASE WHEN %s THEN COALESCE(disabled_by,%s) ELSE NULL END
               WHERE tenant_id=%s AND id=%s""",
            (
                not active,
                not active,
                not active,
                not active,
                not active,
                f"scim:{provider}",
                tenant,
                identifier,
            ),
        )
        if not active:
            self._revoke_sessions(tenant, identifier)
        return _user(row)

    def get_user(self, *, tenant_id: str, domain: str, resource_id: str, for_update: bool = False) -> SCIMUser:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        identifier = _scope(resource_id, "resource_id")
        row = self.connection.execute(
            _USER_GET_FOR_UPDATE_SQL if for_update else _USER_GET_SQL,
            (tenant, provider, identifier),
        ).fetchone()
        if row is None:
            raise SCIMError("SCIM User was not found.", scim_type="invalidValue")
        return _user(row)

    def list_users(
        self,
        *,
        tenant_id: str,
        domain: str,
        filter_attribute: str | None,
        filter_value: str | None,
        offset: int,
        limit: int,
    ) -> tuple[int, tuple[SCIMUser, ...]]:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        count_sql, list_sql, values = self._user_filter(tenant, provider, filter_attribute, filter_value)
        total_row = self.connection.execute(count_sql, values).fetchone()
        rows = self.connection.execute(
            list_sql,
            (*values, limit, offset),
        ).fetchall()
        return int(total_row[0] if total_row else 0), tuple(_user(row) for row in rows)

    def replace_user(
        self,
        *,
        tenant_id: str,
        domain: str,
        resource_id: str,
        expected_version: int,
        resource: SCIMUserWrite,
    ) -> SCIMUser:
        current = self.get_user(tenant_id=tenant_id, domain=domain, resource_id=resource_id, for_update=True)
        if current.version != expected_version:
            raise SCIMError("SCIM resource version does not match.", scim_type="invalidVers")
        if resource.externalId != current.external_id:
            raise SCIMError("externalId cannot be changed by replacement.", scim_type="mutability")
        updated, _ = self.put_user(tenant_id=tenant_id, domain=domain, resource=resource)
        return updated

    def put_group(self, *, tenant_id: str, domain: str, resource: SCIMGroupWrite) -> tuple[SCIMGroup, bool]:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        self._lock_resource(tenant, provider, "Group", resource.externalId)
        member_ids = tuple(sorted(member.value for member in resource.members))
        if member_ids:
            rows = self.connection.execute(
                """SELECT id FROM reconforge.scim_users
                   WHERE tenant_id=%s AND provisioning_domain=%s AND id = ANY(%s) AND active
                   ORDER BY id FOR SHARE""",
                (tenant, provider, list(member_ids)),
            ).fetchall()
            if tuple(str(_value(row, "id", 0)) for row in rows) != member_ids:
                raise SCIMError("SCIM Group contains an unknown or inactive member.")
        existing = self.connection.execute(
            """SELECT id, provisioning_domain, external_id, display_name, version, created_at, updated_at
               FROM reconforge.scim_groups
               WHERE tenant_id=%s AND provisioning_domain=%s AND external_id=%s
               FOR UPDATE""",
            (tenant, provider, resource.externalId),
        ).fetchone()
        created = existing is None
        if created:
            group_id = f"scg-{secrets.token_hex(16)}"
            row = self.connection.execute(
                """INSERT INTO reconforge.scim_groups
                    (tenant_id, provisioning_domain, id, external_id, display_name)
                    VALUES (%s,%s,%s,%s,%s)
                    RETURNING id, provisioning_domain, external_id, display_name, version, created_at, updated_at""",
                (tenant, provider, group_id, resource.externalId, resource.displayName),
            ).fetchone()
            prior_members: tuple[str, ...] = ()
        else:
            group_id = str(_value(existing, "id", 0))
            prior_members = tuple(
                str(_value(item, "user_id", 0))
                for item in self.connection.execute(
                    """SELECT user_id FROM reconforge.scim_group_members
                       WHERE tenant_id=%s AND provisioning_domain=%s AND group_id=%s ORDER BY user_id""",
                    (tenant, provider, group_id),
                ).fetchall()
            )
            current_name = str(_value(existing, "display_name", 3))
            if current_name == resource.displayName and prior_members == member_ids:
                return self._group(existing, prior_members), False
            row = self.connection.execute(
                """UPDATE reconforge.scim_groups SET display_name=%s, version=version+1, updated_at=now()
                    WHERE tenant_id=%s AND provisioning_domain=%s AND id=%s
                    RETURNING id, provisioning_domain, external_id, display_name, version, created_at, updated_at""",
                (resource.displayName, tenant, provider, group_id),
            ).fetchone()
        if row is None:
            raise SCIMError("SCIM group mutation did not return a resource.")
        self.connection.execute(
            "DELETE FROM reconforge.scim_group_members WHERE tenant_id=%s AND provisioning_domain=%s AND group_id=%s",
            (tenant, provider, group_id),
        )
        if member_ids:
            for member_id in member_ids:
                self.connection.execute(
                    """INSERT INTO reconforge.scim_group_members
                       (tenant_id, provisioning_domain, group_id, user_id) VALUES (%s,%s,%s,%s)""",
                    (tenant, provider, group_id, member_id),
                )
        return self._group(row, member_ids), created

    def get_group(self, *, tenant_id: str, domain: str, resource_id: str, for_update: bool = False) -> SCIMGroup:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        identifier = _scope(resource_id, "resource_id")
        row = self.connection.execute(
            _GROUP_GET_FOR_UPDATE_SQL if for_update else _GROUP_GET_SQL,
            (tenant, provider, identifier),
        ).fetchone()
        if row is None:
            raise SCIMError("SCIM Group was not found.", scim_type="invalidValue")
        members = tuple(
            str(_value(item, "user_id", 0))
            for item in self.connection.execute(
                """SELECT user_id FROM reconforge.scim_group_members
                   WHERE tenant_id=%s AND provisioning_domain=%s AND group_id=%s ORDER BY user_id""",
                (tenant, provider, identifier),
            ).fetchall()
        )
        return self._group(row, members)

    def list_groups(
        self,
        *,
        tenant_id: str,
        domain: str,
        filter_attribute: str | None,
        filter_value: str | None,
        offset: int,
        limit: int,
    ) -> tuple[int, tuple[SCIMGroup, ...]]:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        count_sql, list_sql, values = self._group_filter(tenant, provider, filter_attribute, filter_value)
        total_row = self.connection.execute(count_sql, values).fetchone()
        rows = self.connection.execute(
            list_sql,
            (*values, limit, offset),
        ).fetchall()
        resources = tuple(
            self.get_group(tenant_id=tenant, domain=provider, resource_id=str(_value(row, "id", 0))) for row in rows
        )
        return int(total_row[0] if total_row else 0), resources

    def replace_group(
        self,
        *,
        tenant_id: str,
        domain: str,
        resource_id: str,
        expected_version: int,
        resource: SCIMGroupWrite,
    ) -> SCIMGroup:
        current = self.get_group(tenant_id=tenant_id, domain=domain, resource_id=resource_id, for_update=True)
        if current.version != expected_version:
            raise SCIMError("SCIM resource version does not match.", scim_type="invalidVers")
        if resource.externalId != current.external_id:
            raise SCIMError("externalId cannot be changed by replacement.", scim_type="mutability")
        updated, _ = self.put_group(tenant_id=tenant_id, domain=domain, resource=resource)
        return updated

    def delete_group(self, *, tenant_id: str, domain: str, resource_id: str, expected_version: int) -> SCIMGroup:
        tenant, provider = _tenant(tenant_id), _scope(domain, "provisioning_domain")
        current = self.get_group(tenant_id=tenant, domain=provider, resource_id=resource_id, for_update=True)
        if current.version != expected_version:
            raise SCIMError("SCIM resource version does not match.", scim_type="invalidVers")
        self.connection.execute(
            "DELETE FROM reconforge.scim_groups WHERE tenant_id=%s AND provisioning_domain=%s AND id=%s",
            (tenant, provider, current.id),
        )
        return current

    def _revoke_sessions(self, tenant_id: str, user_id: str) -> None:
        self.connection.execute(
            """UPDATE reconforge.identity_sessions
               SET revoked_at=now(), revocation_reason_code='scim_deactivation',
                   revoked_by=%s, lifecycle_version=lifecycle_version+1
               WHERE tenant_id=%s AND user_id=%s AND revoked_at IS NULL""",
            (user_id, tenant_id, user_id),
        )

    def _lock_resource(self, tenant_id: str, domain: str, resource_type: str, external_id: str) -> None:
        """Serialize one external resource identity inside the caller transaction."""

        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"scim:{tenant_id}:{domain}:{resource_type}:{external_id}",),
        )

    @staticmethod
    def _user_filter(
        tenant: str, provider: str, attribute: str | None, value: str | None
    ) -> tuple[str, str, tuple[Any, ...]]:
        if attribute is None:
            return (
                "SELECT count(*) FROM reconforge.scim_users WHERE tenant_id=%s AND provisioning_domain=%s",
                _USER_LIST_SQL,
                (tenant, provider),
            )
        if attribute == "username":
            return (
                "SELECT count(*) FROM reconforge.scim_users WHERE tenant_id=%s AND provisioning_domain=%s AND username=%s",
                _USER_LIST_USERNAME_SQL,
                (tenant, provider, value),
            )
        if attribute == "externalid":
            return (
                "SELECT count(*) FROM reconforge.scim_users WHERE tenant_id=%s AND provisioning_domain=%s AND external_id=%s",
                _USER_LIST_EXTERNAL_SQL,
                (tenant, provider, value),
            )
        raise SCIMError("SCIM filter is not supported.", scim_type="invalidFilter")

    @staticmethod
    def _group_filter(
        tenant: str, provider: str, attribute: str | None, value: str | None
    ) -> tuple[str, str, tuple[Any, ...]]:
        if attribute is None:
            return (
                "SELECT count(*) FROM reconforge.scim_groups WHERE tenant_id=%s AND provisioning_domain=%s",
                _GROUP_LIST_SQL,
                (tenant, provider),
            )
        if attribute == "displayname":
            return (
                "SELECT count(*) FROM reconforge.scim_groups WHERE tenant_id=%s AND provisioning_domain=%s AND display_name=%s",
                _GROUP_LIST_NAME_SQL,
                (tenant, provider, value),
            )
        if attribute == "externalid":
            return (
                "SELECT count(*) FROM reconforge.scim_groups WHERE tenant_id=%s AND provisioning_domain=%s AND external_id=%s",
                _GROUP_LIST_EXTERNAL_SQL,
                (tenant, provider, value),
            )
        raise SCIMError("SCIM filter is not supported.", scim_type="invalidFilter")

    @staticmethod
    def _group(row: Any, members: tuple[str, ...]) -> SCIMGroup:
        return SCIMGroup(
            id=str(_value(row, "id", 0)),
            provisioning_domain=str(_value(row, "provisioning_domain", 1)),
            external_id=str(_value(row, "external_id", 2)),
            display_name=str(_value(row, "display_name", 3)),
            member_ids=members,
            version=int(_value(row, "version", 4)),
            created_at=_time(_value(row, "created_at", 5)),
            updated_at=_time(_value(row, "updated_at", 6)),
        )


class PostgresSCIMAuditSink:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def record(
        self,
        *,
        tenant_id: str,
        domain: str,
        actor_id: str,
        resource_type: Literal["User", "Group"],
        resource_id: str,
        action: str,
        outcome: Literal["ALLOWED", "DENIED"],
        reason_code: str | None,
    ) -> None:
        tenant, provider, actor = (
            _tenant(tenant_id),
            _scope(domain, "provisioning_domain"),
            _scope(actor_id, "actor_id"),
        )
        safe_reason = _scope(reason_code, "reason_code") if reason_code is not None else None
        if resource_type not in {"User", "Group"} or action not in {
            "CREATE",
            "REPLACE",
            "DEACTIVATE",
            "DELETE",
            "PROVISION",
        }:
            raise SCIMError("SCIM audit event is invalid.")
        self.connection.execute(
            """INSERT INTO reconforge.scim_events
               (tenant_id,id,provisioning_domain,actor_id,resource_type,resource_id,action,outcome,reason_code)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                tenant,
                f"sce-{secrets.token_hex(16)}",
                provider,
                actor,
                resource_type,
                resource_id,
                action,
                outcome,
                safe_reason,
            ),
        )


def scim_resource_etag(resource: SCIMUser | SCIMGroup) -> str:
    """Return a weak ETag that reveals no provisioning identifier."""

    digest = hashlib.sha256(f"{resource.id}:{resource.version}".encode()).hexdigest()[:24]
    return f'W/"{digest}"'
