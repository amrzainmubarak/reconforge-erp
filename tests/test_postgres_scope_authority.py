from __future__ import annotations

import os
import re
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import (
    POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL,
    PostgresScopeAuthorityRepository,
)


class _Cursor:
    rowcount = 1

    def __init__(self, rows: list[tuple[str, str]] | None = None) -> None:
        self._rows = rows or []

    def fetchall(self) -> list[tuple[str, str]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[tuple[str, str]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = None) -> _Cursor:
        self.calls.append((sql, params))
        return _Cursor(self.rows)


def test_scope_authority_schema_is_append_only_forced_rls_and_validates_targets() -> None:
    sql = POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL
    assert "principal_scope_grants_active_unique" in sql
    assert "scope grants are immutable; revoke instead" in sql
    assert "scope grant workspace is not registered" in sql
    assert "scope grant legal entity is not registered" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql


def test_scope_snapshot_is_deterministic_and_unknown_principal_fails_closed() -> None:
    connection = _Connection(
        [("workspace", "ws-b"), ("legal_entity", "entity-a"), ("workspace", "ws-a")]
    )
    repository = PostgresScopeAuthorityRepository(connection)
    snapshot = repository.active_for_principal(
        tenant_id="tenant-a", principal_type="user", principal_id="user-a"
    )
    assert snapshot.workspace_ids == frozenset({"ws-a", "ws-b"})
    assert snapshot.legal_entity_ids == frozenset({"entity-a"})
    assert repository.active_for_principal(
        tenant_id="tenant-a", principal_type="invalid", principal_id="user-a"  # type: ignore[arg-type]
    ).workspace_ids == frozenset()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_scope_authority_validates_grants_snapshots_and_revocation() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant, user, workspace = f"authority_{token}", f"user_{token}", f"ws_{token}"
    grant = f"grant_{token}"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE ON reconforge.principal_scope_grants TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT ON reconforge.identity_users,reconforge.service_accounts,"
                f"reconforge.domain_workspaces,reconforge.organizations,reconforge.legal_entities TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                (tenant, workspace, workspace),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_users"
                "(tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm) "
                "VALUES(%s,%s,%s,%s,'hash','salt',100000,'pbkdf2_sha256')",
                (tenant, user, user, user),
            )
        with PostgresTenantBoundary(app_factory).transaction(tenant) as connection:
            repository = PostgresScopeAuthorityRepository(connection)
            repository.grant(
                tenant_id=tenant,
                grant_id=grant,
                principal_type="user",
                principal_id=user,
                scope_type="workspace",
                scope_id=workspace,
                actor_id=user,
            )
            assert repository.active_for_principal(
                tenant_id=tenant, principal_type="user", principal_id=user
            ).workspace_ids == frozenset({workspace})
            repository.revoke(tenant_id=tenant, grant_id=grant, actor_id=user, reason="role changed")
            assert repository.active_for_principal(
                tenant_id=tenant, principal_type="user", principal_id=user
            ).workspace_ids == frozenset()
            with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
                repository.grant(
                    tenant_id=tenant,
                    grant_id=f"missing_{token}",
                    principal_type="user",
                    principal_id=user,
                    scope_type="workspace",
                    scope_id=f"missing_{token}",
                    actor_id=user,
                )
    finally:
        # Grants are append-only; disposable live databases are torn down as a unit.
        admin.close()
