from __future__ import annotations

import os
import re

import pytest

from reconforge.infrastructure.postgres_privileged_sessions import (
    POSTGRES_ACTIVE_ASSURANCE_QUERY,
    POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL,
)


def test_privileged_session_schema_is_forced_rls_append_only_and_bounded() -> None:
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    assert "password_reauthentication" in POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    assert "interval '15 minutes'" in POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    assert "append-only" in POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    assert "token_hash" not in POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    assert "password_hash" not in POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL


def test_active_assurance_prefers_user_verified_webauthn_without_random_id_ties() -> None:
    assert "CASE method WHEN 'webauthn_user_verified' THEN 1 ELSE 0 END DESC" in POSTGRES_ACTIVE_ASSURANCE_QUERY
    assert "verified_at DESC" in POSTGRES_ACTIVE_ASSURANCE_QUERY
    assert "id DESC" in POSTGRES_ACTIVE_ASSURANCE_QUERY


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_password_step_up_is_session_bound_expiring_append_only_and_tenant_isolated() -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL, PostgresIdentityRepository
    from reconforge.infrastructure.postgres_privileged_sessions import PostgresPrivilegedSessionRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "step_up_a", "step_up_b"
    tables = (
        "identity_step_up_assertions",
        "identity_sessions",
        "identity_user_roles",
        "identity_role_permissions",
        "identity_users",
        "identity_permissions",
        "identity_roles",
    )
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL)
            admin.execute(
                "ALTER TABLE reconforge.identity_step_up_assertions DISABLE TRIGGER identity_step_up_assertions_append_only"
            )
            for table in tables:
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            admin.execute(
                "ALTER TABLE reconforge.identity_step_up_assertions ENABLE TRIGGER identity_step_up_assertions_append_only"
            )
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.tenants,"
                    f"reconforge.identity_roles,reconforge.identity_permissions,"
                    f"reconforge.identity_role_permissions,reconforge.identity_users,"
                    f"reconforge.identity_user_roles,reconforge.identity_sessions,"
                    f"reconforge.identity_step_up_assertions TO {app_user}"
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="controller")
            identity.create_permission(tenant_id=tenant_a, permission_name="roles.manage")
            identity.grant_permission(tenant_id=tenant_a, role_name="controller", permission_name="roles.manage")
            user = identity.create_user(
                tenant_id=tenant_a,
                user_id="human-controller",
                username="controller",
                password="Strong-password-123",
                role_name="controller",
            )
            session = identity.create_session(tenant_id=tenant_a, user_id=user.id)
            repository = PostgresPrivilegedSessionRepository(connection)
            before = repository.assurance_for_token(tenant_id=tenant_a, token=session.token, user_id=user.id)
            assert before is not None and not before.step_up_active
            assert repository.reauthenticate(
                tenant_id=tenant_a,
                token=session.token,
                user_id=user.id,
                username=user.username,
                password="wrong-password",
            ) is None
            active = repository.reauthenticate(
                tenant_id=tenant_a,
                token=session.token,
                user_id=user.id,
                username=user.username,
                password="Strong-password-123",
                request_id="request-step-up",
            )
            assert active is not None and active.step_up_active and active.session_id == session.id
            assert repository.assurance_for_token(
                tenant_id=tenant_a, token=session.token, user_id=user.id
            ).step_up_active
            stored = connection.execute(
                "SELECT method,request_id,expires_at <= verified_at + interval '15 minutes' "
                "FROM reconforge.identity_step_up_assertions"
            ).fetchone()
            assert tuple(stored) == ("password_reauthentication", "request-step-up", True)
            with pytest.raises(Exception, match="append-only"), connection.transaction():
                connection.execute("DELETE FROM reconforge.identity_step_up_assertions")
            assert identity.revoke_token(tenant_id=tenant_a, token=session.token)
            assert repository.assurance_for_token(tenant_id=tenant_a, token=session.token, user_id=user.id) is None
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert (
                PostgresPrivilegedSessionRepository(connection).assurance_for_token(
                    tenant_id=tenant_b, token=session.token, user_id=user.id
                )
                is None
            )
            assert connection.execute("SELECT count(*) FROM reconforge.identity_step_up_assertions").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.identity_step_up_assertions DISABLE TRIGGER identity_step_up_assertions_append_only"
                )
                for table in tables:
                    admin.execute(
                        f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                        (tenant_a, tenant_b),
                    )
                admin.execute(
                    "ALTER TABLE reconforge.identity_step_up_assertions ENABLE TRIGGER identity_step_up_assertions_append_only"
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        finally:
            admin.close()
