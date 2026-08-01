from __future__ import annotations

import os
import re

import pytest

from reconforge.infrastructure.postgres_webauthn import POSTGRES_WEBAUTHN_SCHEMA_SQL, WebAuthnRepositoryError


def test_webauthn_schema_is_forced_rls_public_key_only_and_append_only() -> None:
    normalized = " ".join(POSTGRES_WEBAUTHN_SCHEMA_SQL.lower().split())
    for table in (
        "identity_webauthn_challenges",
        "identity_webauthn_credentials",
        "identity_webauthn_events",
    ):
        assert f"alter table reconforge.{table} force row level security" in normalized
    assert "public_key text not null" in normalized
    assert "secret" not in normalized
    assert "identity_webauthn_events_append_only" in normalized
    assert "identity_webauthn_challenge_guard" in normalized
    assert "expires_at<=created_at+interval '5 minutes'" in normalized


def test_webauthn_repository_rejects_invalid_stored_binary() -> None:
    from reconforge.infrastructure.postgres_webauthn import _unb64

    with pytest.raises(WebAuthnRepositoryError):
        _unb64("%%%")


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_webauthn_challenge_public_key_counter_assurance_and_rls() -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
    from reconforge.infrastructure.postgres_privileged_sessions import PostgresPrivilegedSessionRepository
    from reconforge.infrastructure.postgres_webauthn import PostgresWebAuthnRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "webauthn_a", "webauthn_b"
    tables = (
        "identity_webauthn_events",
        "identity_step_up_assertions",
        "identity_webauthn_challenges",
        "identity_webauthn_credentials",
        "identity_sessions",
        "identity_user_roles",
        "identity_role_permissions",
        "identity_users",
        "identity_permissions",
        "identity_roles",
    )
    try:
        with admin.transaction():
            admin.execute(
                "ALTER TABLE reconforge.identity_webauthn_events DISABLE TRIGGER identity_webauthn_events_append_only"
            )
            admin.execute(
                "ALTER TABLE reconforge.identity_step_up_assertions DISABLE TRIGGER identity_step_up_assertions_append_only"
            )
            for table in tables:
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            admin.execute(
                "ALTER TABLE reconforge.identity_webauthn_events ENABLE TRIGGER identity_webauthn_events_append_only"
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
                admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
                admin.execute(f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="operator")
            user = identity.create_user(
                tenant_id=tenant_a,
                user_id="webauthn-user",
                username="webauthn-user",
                password="Strong-password-123",
                role_name="operator",
            )
            session = identity.create_session(tenant_id=tenant_a, user_id=user.id)
            repository = PostgresWebAuthnRepository(connection)
            challenge = repository.issue_challenge(
                tenant_id=tenant_a,
                user_id=user.id,
                session_id=session.id,
                ceremony="authentication",
                request_id="issue-1",
            )
            consumed = repository.consume_challenge(
                tenant_id=tenant_a,
                challenge_id=challenge.id,
                user_id=user.id,
                session_id=session.id,
                ceremony="authentication",
                request_id="consume-1",
            )
            assert consumed.challenge == challenge.challenge
            with pytest.raises(WebAuthnRepositoryError, match="already consumed"):
                repository.consume_challenge(
                    tenant_id=tenant_a,
                    challenge_id=challenge.id,
                    user_id=user.id,
                    session_id=session.id,
                    ceremony="authentication",
                )
            credential = repository.register_credential(
                tenant_id=tenant_a,
                user_id=user.id,
                credential_id=b"synthetic-credential",
                public_key=b"synthetic-public-key-only",
                sign_count=0,
                transports=("internal",),
                device_type="single_device",
                backed_up=False,
                label="Synthetic authenticator",
                request_id="register-1",
            )
            repository.record_authentication(
                tenant_id=tenant_a,
                user_id=user.id,
                credential_id=credential.credential_id,
                previous_sign_count=0,
                new_sign_count=1,
                device_type="single_device",
                backed_up=False,
                request_id="verify-1",
            )
            assurance = PostgresPrivilegedSessionRepository(connection).record_webauthn_verification(
                tenant_id=tenant_a,
                token=session.token,
                user_id=user.id,
                credential_id="c3ludGhldGljLWNyZWRlbnRpYWw",
                request_id="assure-1",
            )
            assert assurance is not None and assurance.step_up_method == "webauthn_user_verified"
            current = PostgresPrivilegedSessionRepository(connection).assurance_for_token(
                tenant_id=tenant_a, token=session.token, user_id=user.id
            )
            assert current is not None and current.step_up_method == "webauthn_user_verified"
            with pytest.raises(WebAuthnRepositoryError, match="stale"):
                repository.record_authentication(
                    tenant_id=tenant_a,
                    user_id=user.id,
                    credential_id=credential.credential_id,
                    previous_sign_count=0,
                    new_sign_count=2,
                    device_type="single_device",
                    backed_up=False,
                )
            assert connection.execute("SELECT count(*) FROM reconforge.identity_webauthn_events").fetchone()[0] == 4
            with pytest.raises(Exception, match="append-only"), connection.transaction():
                connection.execute("DELETE FROM reconforge.identity_webauthn_events")
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.identity_webauthn_credentials").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.identity_webauthn_events").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.identity_webauthn_events DISABLE TRIGGER identity_webauthn_events_append_only"
                )
                admin.execute(
                    "ALTER TABLE reconforge.identity_step_up_assertions DISABLE TRIGGER identity_step_up_assertions_append_only"
                )
                for table in tables:
                    admin.execute(
                        f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                        (tenant_a, tenant_b),
                    )
                admin.execute(
                    "ALTER TABLE reconforge.identity_webauthn_events ENABLE TRIGGER identity_webauthn_events_append_only"
                )
                admin.execute(
                    "ALTER TABLE reconforge.identity_step_up_assertions ENABLE TRIGGER identity_step_up_assertions_append_only"
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        finally:
            admin.close()
