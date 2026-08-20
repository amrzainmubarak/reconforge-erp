from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.db import run_migrations

pytest.importorskip("cbor2", reason="webauthn cbor2 extra is optional")
pytest.importorskip("cryptography", reason="webauthn crypto extra is optional")


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_http_webauthn_enrollment_mfa_step_up_replay_and_tenant_scope(
    tmp_path: Path,
) -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "webauthn_http_a", "webauthn_http_b"
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
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant in (tenant_a, tenant_b):
        run_migrations(root / f"{tenant}.db")
    try:
        with admin.transaction():
            for trigger, table in (
                ("identity_webauthn_events_append_only", "identity_webauthn_events"),
                ("identity_step_up_assertions_append_only", "identity_step_up_assertions"),
                ("principal_scope_grants_guard", "principal_scope_grants"),
            ):
                admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER {trigger}")
            for table in ("principal_scope_grants", *tables):
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            for trigger, table in (
                ("identity_webauthn_events_append_only", "identity_webauthn_events"),
                ("identity_step_up_assertions_append_only", "identity_step_up_assertions"),
                ("principal_scope_grants_guard", "principal_scope_grants"),
            ):
                admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER {trigger}")
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
            identity.create_permission(tenant_id=tenant_a, permission_name="finance_core.validate")
            identity.grant_permission(
                tenant_id=tenant_a, role_name="operator", permission_name="finance_core.validate"
            )
            identity.create_user(
                tenant_id=tenant_a,
                user_id="http-webauthn-user",
                username="webauthn-user",
                password="Strong-password-123",
                role_name="operator",
            )
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                (tenant_a, "webauthn-workspace", "WebAuthn test workspace"),
            )
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=tenant_a,
                grant_id="webauthn-http-user-workspace",
                principal_type="user",
                principal_id="http-webauthn-user",
                scope_type="workspace",
                scope_id="webauthn-workspace",
                actor_id="http-webauthn-user",
            )
        runtime = WebAuthnRuntime(
            rp_id="example.test",
            rp_name="ReconForge Test",
            allowed_origins=("https://example.test",),
        )
        client = TestClient(
            create_api_app(
                tmp_path / "unused.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
                webauthn_runtime=runtime,
            )
        )
        tenant_headers = {
            "X-ReconForge-Tenant": tenant_a,
            "X-ReconForge-Workspace": "webauthn-workspace",
        }
        login = client.post(
            "/api/v1/auth/login",
            headers=tenant_headers,
            json={"username": "webauthn-user", "password": "Strong-password-123"},
        )
        assert login.status_code == 200
        headers = {**tenant_headers, "Authorization": f"Bearer {login.json()['access_token']}"}
        denied_enrollment = client.post("/api/v1/auth/webauthn/registration/options", headers=headers)
        stepped = client.post(
            "/api/v1/auth/step-up", headers=headers, json={"password": "Strong-password-123"}
        )
        assert denied_enrollment.status_code == 403
        assert stepped.status_code == 200
        password_only_privileged = client.get("/api/v1/finance-core/summary", headers=headers)
        assert password_only_privileged.status_code == 403
        assert password_only_privileged.json()["error"]["code"] == "mfa_required"
        options = client.post("/api/v1/auth/webauthn/registration/options", headers=headers)
        assert options.status_code == 200, options.text
        assert options.json()["public_key"]["authenticatorSelection"]["userVerification"] == "required"
        credential_id = b"http-synthetic-webauthn-credential"
        from cryptography.hazmat.primitives.asymmetric import ec
        private_key = ec.generate_private_key(ec.SECP256R1())
        from tests.webauthn_synthetic import authentication_response, registration_response
        registration_credential = registration_response(
            challenge=base64.urlsafe_b64decode(options.json()["public_key"]["challenge"] + "=="),
            rp_id=runtime.rp_id,
            origin=runtime.allowed_origins[0],
            credential_id=credential_id,
            private_key=private_key,
        )
        registered = client.post(
            "/api/v1/auth/webauthn/registration/verify",
            headers=headers,
            json={"challenge_id": options.json()["challenge_id"], "credential": registration_credential, "label": "Test key"},
        )
        replay_registration = client.post(
            "/api/v1/auth/webauthn/registration/verify",
            headers=headers,
            json={"challenge_id": options.json()["challenge_id"], "credential": registration_credential, "label": "Test key"},
        )
        assert registered.status_code == 200, registered.text
        assert replay_registration.status_code == 409
        auth_options = client.post("/api/v1/auth/webauthn/authentication/options", headers=headers)
        assert auth_options.status_code == 200, auth_options.text
        authentication_credential = authentication_response(
            challenge=base64.urlsafe_b64decode(auth_options.json()["public_key"]["challenge"] + "=="),
            rp_id=runtime.rp_id,
            origin=runtime.allowed_origins[0],
            credential_id=credential_id,
            private_key=private_key,
            sign_count=1,
        )
        verified = client.post(
            "/api/v1/auth/webauthn/authentication/verify",
            headers=headers,
            json={"challenge_id": auth_options.json()["challenge_id"], "credential": authentication_credential},
        )
        me = client.get("/api/v1/auth/me", headers=headers)
        cross_tenant = client.post(
            "/api/v1/auth/webauthn/authentication/options",
            headers={**headers, "X-ReconForge-Tenant": tenant_b},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["method"] == "webauthn_user_verified"
        assert me.status_code == 200 and me.json()["step_up_method"] == "webauthn_user_verified"
        assert client.get("/api/v1/finance-core/summary", headers=headers).status_code == 200
        assert cross_tenant.status_code == 401
    finally:
        admin.close()


def test_webauthn_routes_are_disabled_without_explicit_runtime(tmp_path: Path) -> None:
    db_path = tmp_path / "local.db"
    run_migrations(db_path)
    client = TestClient(create_api_app(db_path))
    response = client.post("/api/v1/auth/webauthn/authentication/options")

    assert response.status_code == 401
