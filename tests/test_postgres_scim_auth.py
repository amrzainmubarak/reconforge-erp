from __future__ import annotations

import hashlib
import os
import re
from datetime import timedelta
from typing import Any

import pytest

from reconforge.auth.scim import SCIMError
from reconforge.infrastructure.postgres_scim_auth import (
    POSTGRES_SCIM_AUTH_SCHEMA_SQL,
    PostgresSCIMCredentialRepository,
)


class Cursor:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []
        self.authenticated = True

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> Cursor:
        self.calls.append((sql, parameters))
        normalized = " ".join(sql.split()).lower()
        if "returning provisioning_domain, client_id, id" in normalized and self.authenticated:
            return Cursor(("corp-idp", "entra-scim", "scc-0123456789abcdef0123456789abcdef"))
        if "returning id" in normalized:
            return Cursor(("scc-0123456789abcdef0123456789abcdef",))
        return Cursor()


def test_scim_credential_schema_is_hash_only_forced_rls() -> None:
    assert POSTGRES_SCIM_AUTH_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 1
    assert "token_hash TEXT" in POSTGRES_SCIM_AUTH_SCHEMA_SQL
    assert "token TEXT" not in POSTGRES_SCIM_AUTH_SCHEMA_SQL
    assert "UNIQUE (tenant_id, token_hash)" in POSTGRES_SCIM_AUTH_SCHEMA_SQL
    assert "expires_at > created_at" in POSTGRES_SCIM_AUTH_SCHEMA_SQL


def test_issue_returns_raw_once_but_persists_only_hash() -> None:
    connection = Connection()
    issued = PostgresSCIMCredentialRepository(connection).issue(
        tenant_id="tenant-a",
        provisioning_domain="corp-idp",
        client_id="entra-scim",
        actor_id="security-admin",
        ttl=timedelta(days=30),
    )
    _, parameters = connection.calls[-1]
    assert parameters is not None
    assert issued.token.startswith("rfs_")
    assert issued.token not in parameters
    assert hashlib.sha256(issued.token.encode()).hexdigest() in parameters


@pytest.mark.parametrize("ttl", [timedelta(seconds=1), timedelta(days=367)])
def test_issue_rejects_unsafe_lifetimes(ttl: timedelta) -> None:
    with pytest.raises(SCIMError, match="lifetime"):
        PostgresSCIMCredentialRepository(Connection()).issue(
            tenant_id="tenant-a",
            provisioning_domain="corp-idp",
            client_id="entra-scim",
            actor_id="security-admin",
            ttl=ttl,
        )


def test_authentication_hashes_token_and_returns_server_scoped_principal() -> None:
    connection = Connection()
    token = "rfs_" + "a" * 64
    principal = PostgresSCIMCredentialRepository(connection).authenticate(tenant_id="tenant-a", token=token)
    assert principal is not None
    assert (principal.tenant_id, principal.provisioning_domain, principal.client_id) == (
        "tenant-a",
        "corp-idp",
        "entra-scim",
    )
    _, parameters = connection.calls[-1]
    assert parameters == ("tenant-a", hashlib.sha256(token.encode()).hexdigest())
    assert token not in repr(connection.calls)


def test_invalid_or_revoked_credential_fails_closed() -> None:
    connection = Connection()
    repository = PostgresSCIMCredentialRepository(connection)
    assert repository.authenticate(tenant_id="tenant-a", token="short") is None
    connection.authenticated = False
    assert repository.authenticate(tenant_id="tenant-a", token="rfs_" + "b" * 64) is None


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_scim_credential_rotation_revocation_expiry_and_rls() -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "scim_auth_a", "scim_auth_b"
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_SCIM_AUTH_SCHEMA_SQL)
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, reconforge.scim_credentials TO {app_user}"
                )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute("INSERT INTO reconforge.tenants (id,name) VALUES (%s,%s)", (tenant, tenant))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresSCIMCredentialRepository(connection)
            first = repository.issue(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                client_id="entra-scim",
                actor_id="security-admin",
                ttl=timedelta(days=30),
            )
            assert repository.authenticate(tenant_id=tenant_a, token=first.token) is not None
            rotated = repository.issue(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                client_id="entra-scim",
                actor_id="security-admin",
                ttl=timedelta(days=30),
                rotated_from_id=first.id,
            )
            assert repository.authenticate(tenant_id=tenant_a, token=first.token) is None
            assert repository.authenticate(tenant_id=tenant_a, token=rotated.token) is not None
            assert repository.revoke(tenant_id=tenant_a, credential_id=rotated.id, actor_id="security-admin")
            assert repository.authenticate(tenant_id=tenant_a, token=rotated.token) is None
            stored = connection.execute(
                "SELECT token_hash FROM reconforge.scim_credentials ORDER BY created_at"
            ).fetchall()
            assert all(value[0] not in {first.token, rotated.token} for value in stored)
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.scim_credentials").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "DELETE FROM reconforge.scim_credentials WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b)
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        finally:
            admin.close()
