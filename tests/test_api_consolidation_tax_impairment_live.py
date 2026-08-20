from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from tests.test_consolidation_deferred_tax import _request as deferred_tax_request
from tests.test_consolidation_impairment import _request as impairment_request


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_consolidation_tax_and_impairment_api_is_replayable_and_tenant_isolated(
    tmp_path: Path,
) -> None:
    """Exercise both non-posting acquisition evidence APIs on a clean server profile."""

    pytest.importorskip("psycopg")
    from alembic.config import Config

    from alembic import command
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
    )
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    token = uuid4().hex[:8]
    tenant_a = f"tax_api_a_{token}"
    tenant_b = f"tax_api_b_{token}"
    preparer = "api-preparer"
    reviewer = "api-reviewer"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = None
    try:
        admin = admin_factory.connect()
        previous_migration_dsn = os.environ.get("RECONFORGE_POSTGRES_DSN")
        os.environ["RECONFORGE_POSTGRES_DSN"] = admin_dsn
        try:
            command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
        finally:
            if previous_migration_dsn is None:
                os.environ.pop("RECONFORGE_POSTGRES_DSN", None)
            else:
                os.environ["RECONFORGE_POSTGRES_DSN"] = previous_migration_dsn
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                f"reconforge.identity_sessions, reconforge.identity_step_up_assertions, "
                f"reconforge.emergency_access_requests, reconforge.emergency_access_permissions, "
                f"reconforge.emergency_access_events, "
                f"reconforge.domain_workspaces, reconforge.principal_scope_grants, "
                f"reconforge.consolidation_deferred_tax_artifacts, "
                f"reconforge.consolidation_impairment_artifacts, "
                f"reconforge.domain_audit_ledger_state, reconforge.domain_audit_events TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )

        role = app_factory.connect()
        try:
            role_flags = role.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
        finally:
            role.close()
        if role_flags is None or bool(role_flags[0]) or bool(role_flags[1]):
            pytest.skip("live evidence API requires a non-superuser, non-BYPASSRLS role")

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="Admin")
            identity.create_permission(tenant_id=tenant_a, permission_name="finance_core.read")
            identity.create_permission(tenant_id=tenant_a, permission_name="finance_core.manage")
            identity.grant_permission(
                tenant_id=tenant_a, role_name="admin", permission_name="finance_core.read"
            )
            identity.grant_permission(
                tenant_id=tenant_a, role_name="admin", permission_name="finance_core.manage"
            )
            identity.create_user(
                tenant_id=tenant_a,
                user_id=preparer,
                username="preparer",
                password="Strong-password-123",
                role_name="admin",
            )
            identity.create_user(
                tenant_id=tenant_a,
                user_id=reviewer,
                username="reviewer",
                password="Strong-password-123",
                role_name="admin",
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            base_headers = {"X-ReconForge-Tenant": tenant_a}
            login = client.post(
                "/api/v1/auth/login",
                headers=base_headers,
                json={"username": "preparer", "password": "Strong-password-123"},
            )
            assert login.status_code == 200, login.text
            headers = {
                **base_headers,
                "Authorization": f"Bearer {login.json()['access_token']}",
            }
            step_up = client.post(
                "/api/v1/auth/step-up",
                headers=headers,
                json={"password": "Strong-password-123"},
            )
            assert step_up.status_code == 200, step_up.text

            cases = (
                (
                    "/api/v1/consolidation-deferred-tax",
                    deferred_tax_request(prepared_by=preparer, approved_by=reviewer).to_dict(),
                    "dtax-",
                    "postgresql-consolidation-deferred-tax",
                ),
                (
                    "/api/v1/consolidation-impairment",
                    impairment_request(prepared_by=preparer, approved_by=reviewer).to_dict(),
                    "imp-",
                    "postgresql-consolidation-impairment",
                ),
            )
            for endpoint, payload, artifact_prefix, source_kind in cases:
                payload.pop("prepared_by", None)
                created = client.post(endpoint, headers=headers, json=payload)
                assert created.status_code == 200, created.text
                assert created.json()["artifact"]["posted"] is False
                assert created.json()["source"]["kind"] == source_kind
                artifact_id = created.json()["artifact"]["id"]
                assert artifact_id.startswith(artifact_prefix)

                repeated = client.post(endpoint, headers=headers, json=payload)
                assert repeated.status_code == 200, repeated.text
                assert repeated.json()["artifact"]["id"] == artifact_id

                loaded = client.get(f"{endpoint}/{artifact_id}", headers=headers)
                assert loaded.status_code == 200, loaded.text
                assert loaded.json()["artifact"]["result_payload"]["posted"] is False

                cross_tenant = client.get(
                    f"{endpoint}/{artifact_id}",
                    headers={**headers, "X-ReconForge-Tenant": tenant_b},
                )
                assert cross_tenant.status_code == 401
    finally:
        if admin is not None:
            try:
                with admin.transaction():
                    admin.execute(
                        "ALTER TABLE reconforge.consolidation_deferred_tax_artifacts "
                        "DISABLE TRIGGER consolidation_deferred_tax_artifact_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.consolidation_impairment_artifacts "
                        "DISABLE TRIGGER consolidation_impairment_artifact_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.domain_audit_events "
                        "DISABLE TRIGGER domain_audit_events_immutable"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.identity_step_up_assertions "
                        "DISABLE TRIGGER identity_step_up_assertions_append_only"
                    )
                    for table in (
                        "consolidation_deferred_tax_artifacts",
                        "consolidation_impairment_artifacts",
                    ):
                        admin.execute(
                            f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",
                            (tenant_a, tenant_b),
                        )
                    admin.execute(
                        "DELETE FROM reconforge.domain_audit_events WHERE tenant_id IN (%s,%s)",
                        (tenant_a, tenant_b),
                    )
                    admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
                    admin.execute(
                        "ALTER TABLE reconforge.domain_audit_events "
                        "ENABLE TRIGGER domain_audit_events_immutable"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.identity_step_up_assertions "
                        "ENABLE TRIGGER identity_step_up_assertions_append_only"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.consolidation_impairment_artifacts "
                        "ENABLE TRIGGER consolidation_impairment_artifact_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.consolidation_deferred_tax_artifacts "
                        "ENABLE TRIGGER consolidation_deferred_tax_artifact_guard"
                    )
            finally:
                admin.close()
