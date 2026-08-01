from __future__ import annotations

import hashlib
import os
import re
from datetime import timedelta

import pytest

from reconforge.infrastructure.postgres_service_accounts import (
    FORBIDDEN_SERVICE_PERMISSIONS,
    POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
    PostgresServiceAccountRepository,
    ServiceAccountError,
)


class UnusedConnection:
    def execute(self, *_: object, **__: object) -> None:
        raise AssertionError("invalid input must fail before database access")


def test_service_account_schema_is_hash_only_and_forced_rls() -> None:
    assert POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 4
    assert "token_hash TEXT" in POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL
    assert "token TEXT" not in POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL
    assert "UNIQUE (tenant_id,token_hash)" in POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL
    assert "identity_permissions" in POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL
    assert "service_account_events" in POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL


@pytest.mark.parametrize(
    "permissions",
    [
        frozenset(),
        frozenset({"roles.manage"}),
        frozenset({"payables.approve"}),
        frozenset({"BAD PERMISSION"}),
        frozenset(f"p.{i}" for i in range(33)),
    ],
)
def test_service_account_rejects_empty_forbidden_malformed_or_excessive_grants(
    permissions: frozenset[str],
) -> None:
    assert "roles.manage" in FORBIDDEN_SERVICE_PERMISSIONS
    with pytest.raises(ServiceAccountError):
        PostgresServiceAccountRepository(UnusedConnection()).create_account(
            tenant_id="tenant-a",
            account_id="svc-importer",
            name="importer",
            display_name="Importer",
            permissions=permissions,
            actor_id="security-admin",
        )


@pytest.mark.parametrize("ttl", [timedelta(seconds=1), timedelta(days=91)])
def test_service_account_rejects_unsafe_maximum_credential_lifetime(ttl: timedelta) -> None:
    with pytest.raises(ServiceAccountError, match="lifetime"):
        PostgresServiceAccountRepository(UnusedConnection()).create_account(
            tenant_id="tenant-a",
            account_id="svc-importer",
            name="importer",
            display_name="Importer",
            permissions=frozenset({"db.read"}),
            actor_id="security-admin",
            max_credential_ttl=ttl,
        )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_service_account_least_privilege_rotation_disable_expiry_and_rls() -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "service_account_a", "service_account_b"
    tables = (
        "service_account_events",
        "service_account_credentials",
        "service_account_permissions",
        "service_accounts",
        "identity_role_permissions",
        "identity_user_roles",
        "identity_permissions",
        "identity_roles",
        "identity_sessions",
        "identity_users",
    )
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL)
            admin.execute(
                "ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only"
            )
            for table in tables:
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            admin.execute(
                "ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only"
            )
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            for tenant in (tenant_a, tenant_b):
                admin.execute(
                    """INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
                       VALUES (%s,'db.read','Read'),(%s,'audit.read','Audit'),(%s,'roles.manage','Human only')""",
                    (tenant, tenant, tenant),
                )
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT,INSERT,UPDATE,DELETE ON "
                    f"reconforge.tenants,reconforge.identity_permissions,"
                    f"reconforge.service_accounts,reconforge.service_account_permissions,"
                    f"reconforge.service_account_credentials,reconforge.service_account_events TO {app_user}"
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresServiceAccountRepository(connection)
            account = repository.create_account(
                tenant_id=tenant_a,
                account_id="svc-importer",
                name="importer",
                display_name="Import Worker",
                permissions=frozenset({"db.read"}),
                actor_id="security-admin",
                max_credential_ttl=timedelta(days=7),
            )
            assert account.permissions == frozenset({"db.read"})
            with (
                pytest.raises(Exception, match="service_account_permissions_human_only"),
                connection.transaction(),
            ):
                connection.execute(
                    """INSERT INTO reconforge.service_account_permissions
                       (tenant_id,service_account_id,permission_name,granted_by)
                       VALUES (%s,%s,'roles.manage','attacker')""",
                    (tenant_a, account.id),
                )
            with (
                pytest.raises(Exception, match="service_account_permissions_permission_name_check"),
                connection.transaction(),
            ):
                connection.execute(
                    """INSERT INTO reconforge.service_account_permissions
                       (tenant_id,service_account_id,permission_name,granted_by)
                       VALUES (%s,%s,'payables.approve','attacker')""",
                    (tenant_a, account.id),
                )
            with pytest.raises(Exception, match="version transition"), connection.transaction():
                connection.execute(
                    "UPDATE reconforge.service_accounts SET version=version+2 WHERE tenant_id=%s AND id=%s",
                    (tenant_a, account.id),
                )
            with pytest.raises(Exception, match="credential policy"), connection.transaction():
                connection.execute(
                    """INSERT INTO reconforge.service_account_credentials
                       (tenant_id,id,service_account_id,token_hash,created_by,created_at,expires_at)
                       VALUES (%s,'sac-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',%s,%s,'attacker',now(),now()+interval '8 days')""",
                    (tenant_a, account.id, "a" * 64),
                )
            first = repository.issue_credential(
                tenant_id=tenant_a,
                account_id=account.id,
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
            principal = repository.authenticate(tenant_id=tenant_a, token=first.token)
            assert principal is not None
            assert principal.permissions == frozenset({"db.read"})
            with pytest.raises(ServiceAccountError, match="human-only"):
                repository.replace_permissions(
                    tenant_id=tenant_a,
                    account_id=account.id,
                    permissions=frozenset({"audit.read"}),
                    expected_version=account.version,
                    actor_id="security-admin",
                )
            assert repository.authenticate(tenant_id=tenant_a, token=first.token).permissions == frozenset({"db.read"})
            rotated = repository.issue_credential(
                tenant_id=tenant_a,
                account_id=account.id,
                actor_id="security-admin",
                ttl=timedelta(hours=1),
                rotated_from_id=first.id,
            )
            assert repository.authenticate(tenant_id=tenant_a, token=first.token) is None
            assert repository.authenticate(tenant_id=tenant_a, token=rotated.token) is not None
            disabled = repository.set_enabled(
                tenant_id=tenant_a,
                account_id=account.id,
                enabled=False,
                expected_version=account.version,
                actor_id="security-admin",
            )
            assert not disabled.enabled
            assert repository.authenticate(tenant_id=tenant_a, token=rotated.token) is None
            stored = connection.execute(
                "SELECT token_hash FROM reconforge.service_account_credentials ORDER BY created_at"
            ).fetchall()
            assert {row[0] for row in stored} == {
                hashlib.sha256(first.token.encode()).hexdigest(),
                hashlib.sha256(rotated.token.encode()).hexdigest(),
            }
            assert connection.execute("SELECT count(*) FROM reconforge.service_account_events").fetchone()[0] == 4
            with pytest.raises(Exception, match="append-only"), connection.transaction():
                connection.execute("DELETE FROM reconforge.service_account_events")
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresServiceAccountRepository(connection)
            assert repository.authenticate(tenant_id=tenant_b, token=first.token) is None
            assert connection.execute("SELECT count(*) FROM reconforge.service_accounts").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only"
                )
                for table in tables:
                    admin.execute(
                        f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                        (tenant_a, tenant_b),
                    )
                admin.execute(
                    "ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only"
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        finally:
            admin.close()
