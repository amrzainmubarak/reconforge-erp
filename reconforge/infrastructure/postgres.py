"""Optional PostgreSQL connection and tenant-isolation boundary.

This module deliberately does not import psycopg at module import time.  The
local SQLite installation must remain usable without server dependencies, while
server deployments get a real PostgreSQL connection and database-enforced
tenant scope when the ``server`` extra is installed.

The application role used with the schema in this module must not own the
tables and must not be a PostgreSQL superuser or a role with ``BYPASSRLS``.
Those operational requirements are part of the security boundary and are
documented in the PostgreSQL ADR.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Protocol

_SCOPE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class PostgresConfigurationError(ValueError):
    """Raised when PostgreSQL settings or a tenant scope are unsafe."""


class PostgresUnavailableError(RuntimeError):
    """Raised when the optional PostgreSQL driver is not installed."""


class ConnectionFactory(Protocol):
    """Minimal connection-factory contract used by tenant-scoped services."""

    def connect(self) -> Any:
        """Return a connection supporting ``transaction``, ``execute``, and ``close``."""


def normalize_scope_id(value: str, *, field_name: str = "tenant_id") -> str:
    """Normalize and validate an identifier used in a PostgreSQL scope.

    IDs are intentionally restricted to the same conservative alphabet used by
    the local tenant router.  Values are passed as SQL parameters; this
    validation is an additional defense against accidental scope ambiguity and
    unsafe operational identifiers.
    """

    normalized = str(value or "").strip().lower()
    if not _SCOPE_ID_PATTERN.fullmatch(normalized):
        raise PostgresConfigurationError(
            f"{field_name} must use 1-64 lowercase letters, numbers, hyphens, or underscores."
        )
    return normalized


def validate_tenant_id(tenant_id: str) -> str:
    """Return a validated tenant identifier."""

    return normalize_scope_id(tenant_id, field_name="tenant_id")


def validate_organization_id(organization_id: str | None) -> str | None:
    """Return a validated optional organization identifier."""

    if organization_id is None:
        return None
    return normalize_scope_id(organization_id, field_name="organization_id")


def validate_workspace_id(workspace_id: str | None) -> str | None:
    """Return a validated optional workspace identifier."""

    if workspace_id is None:
        return None
    return normalize_scope_id(workspace_id, field_name="workspace_id")


def validate_legal_entity_id(legal_entity_id: str | None) -> str | None:
    """Return a validated optional legal-entity identifier."""

    if legal_entity_id is None:
        return None
    return normalize_scope_id(legal_entity_id, field_name="legal_entity_id")


@dataclass(frozen=True)
class PostgresExecutionScope:
    """Immutable tenant hierarchy attached to one database transaction.

    Optional child scopes are explicit rather than inferred.  Callers that
    operate tenant-wide leave them unset; entity/workspace-bound use cases must
    provide them so database policies can fail closed at the same boundary.
    """

    tenant_id: str
    organization_id: str | None = None
    workspace_id: str | None = None
    legal_entity_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", validate_tenant_id(self.tenant_id))
        object.__setattr__(self, "organization_id", validate_organization_id(self.organization_id))
        object.__setattr__(self, "workspace_id", validate_workspace_id(self.workspace_id))
        object.__setattr__(self, "legal_entity_id", validate_legal_entity_id(self.legal_entity_id))
        if self.legal_entity_id is not None and self.organization_id is None:
            raise PostgresConfigurationError("legal_entity_id requires organization_id.")


@dataclass(frozen=True)
class PostgresSettings:
    """Connection settings for the optional PostgreSQL server boundary."""

    dsn: str = field(repr=False)
    application_name: str = "reconforge"
    connect_timeout_seconds: int = 10
    statement_timeout_ms: int = 30_000
    require_tls: bool = True

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise PostgresConfigurationError("PostgreSQL DSN must not be blank.")
        if not self.application_name.strip():
            raise PostgresConfigurationError("PostgreSQL application name must not be blank.")
        if self.connect_timeout_seconds <= 0:
            raise PostgresConfigurationError("PostgreSQL connect timeout must be positive.")
        if self.statement_timeout_ms <= 0:
            raise PostgresConfigurationError("PostgreSQL statement timeout must be positive.")


def _load_psycopg() -> ModuleType:
    try:
        return importlib.import_module("psycopg")
    except ImportError as exc:
        raise PostgresUnavailableError(
            "PostgreSQL support is optional. Install the server extra with `pip install 'reconforge-erp[server]'`."
        ) from exc


class PostgresConnectionFactory:
    """Create configured psycopg connections without leaking the DSN."""

    def __init__(self, settings: PostgresSettings) -> None:
        self.settings = settings

    def connect(self) -> Any:
        """Open a PostgreSQL connection with bounded, secure defaults."""

        psycopg = _load_psycopg()
        connect_kwargs: dict[str, Any] = {
            "connect_timeout": self.settings.connect_timeout_seconds,
            "application_name": self.settings.application_name,
            "options": f"-c statement_timeout={self.settings.statement_timeout_ms}",
            "row_factory": _hybrid_row_factory,
        }
        if self.settings.require_tls:
            connect_kwargs["sslmode"] = "verify-full"
        return psycopg.connect(self.settings.dsn, **connect_kwargs)


class _HybridPostgresRow:
    """Expose one immutable driver row by stable name and positional index."""

    __slots__ = ("_index", "_names", "_values")

    def __init__(self, names: tuple[str, ...], values: tuple[object, ...]) -> None:
        self._names = names
        self._values = values
        self._index = {name: index for index, name in enumerate(names)}

    def __getitem__(self, key: str | int | slice) -> object:
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> tuple[str, ...]:
        return self._names

    def get(self, key: str, default: object = None) -> object:
        index = self._index.get(key)
        return default if index is None else self._values[index]


def _hybrid_row_factory(cursor: Any):  # type: ignore[no-untyped-def]
    names = tuple(column.name for column in (cursor.description or ()))

    def make_row(values: tuple[object, ...]) -> _HybridPostgresRow:
        return _HybridPostgresRow(names, values)

    return make_row


def set_local_tenant_scope(
    connection: Any,
    tenant_id: str,
    organization_id: str | None = None,
    *,
    workspace_id: str | None = None,
    legal_entity_id: str | None = None,
) -> PostgresExecutionScope:
    """Set transaction-local tenant context using parameterized SQL.

    ``set_config(..., true)`` is equivalent to ``SET LOCAL`` for the custom
    settings used by the RLS policies.  The transaction-local flag ensures a
    pooled connection cannot retain one request's tenant after commit or
    rollback.
    """

    scope = PostgresExecutionScope(
        tenant_id=tenant_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        legal_entity_id=legal_entity_id,
    )
    connection.execute("SELECT set_config('app.tenant_id', %s, true)", (scope.tenant_id,))
    connection.execute("SELECT set_config('app.organization_id', %s, true)", (scope.organization_id or "",))
    connection.execute("SELECT set_config('app.workspace_id', %s, true)", (scope.workspace_id or "",))
    connection.execute("SELECT set_config('app.legal_entity_id', %s, true)", (scope.legal_entity_id or "",))
    connection.execute("SELECT set_config('app.entity_id', %s, true)", (scope.legal_entity_id or "",))
    return scope


class PostgresTenantBoundary:
    """Own one connection and transaction for a tenant-scoped operation."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    @contextmanager
    def transaction(
        self,
        tenant_id: str,
        *,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> Iterator[Any]:
        """Yield a connection whose current transaction is tenant-scoped."""

        connection = self.connection_factory.connect()
        try:
            with connection.transaction():
                set_local_tenant_scope(
                    connection,
                    tenant_id,
                    organization_id,
                    workspace_id=workspace_id,
                    legal_entity_id=legal_entity_id,
                )
                yield connection
        finally:
            connection.close()


POSTGRES_RLS_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS reconforge;

CREATE TABLE IF NOT EXISTS reconforge.tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reconforge.organizations (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.tenant_memberships (
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, role_name),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

ALTER TABLE reconforge.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.tenant_memberships FORCE ROW LEVEL SECURITY;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge'
          AND tablename = 'tenants'
          AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.tenants
            USING (id = current_setting('app.tenant_id', true))
            WITH CHECK (id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge'
          AND tablename = 'organizations'
          AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.organizations
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge'
          AND tablename = 'tenant_memberships'
          AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.tenant_memberships
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END
$reconforge$;
"""


def install_postgres_rls_schema(connection: Any) -> None:
    """Install the idempotent foundation schema using a caller-owned transaction."""

    connection.execute(POSTGRES_RLS_SCHEMA_SQL)
