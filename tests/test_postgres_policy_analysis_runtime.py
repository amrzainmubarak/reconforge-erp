from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from reconforge.application.policy_analysis import PolicyAnalysisApplicationService
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_policy_analysis import PostgresPolicyAnalysisRepository


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_policy_analysis_is_rls_isolated_and_maker_checker_bound() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"policy_a_{suffix}"
    tenant_b = f"policy_b_{suffix}"
    user_one = f"user_one_{suffix}"
    user_two = f"user_two_{suffix}"
    role_prepare = f"role_prepare_{suffix}"
    role_approve = f"role_approve_{suffix}"
    service_account = f"svc-{suffix}"
    now = datetime.now(UTC).replace(microsecond=0)

    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT ON TABLE reconforge.identity_users, reconforge.identity_roles, "
                f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                f"reconforge.identity_permissions, reconforge.service_accounts, "
                f"reconforge.service_account_permissions TO {app_user}"
            )
            admin.execute(
                """INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
                   VALUES (%s,'close.prepare','prepare'),(%s,'close.approve','approve'),
                          (%s,'close.manage','manage')""",
                (tenant_a, tenant_a, tenant_a),
            )
            admin.execute(
                """INSERT INTO reconforge.identity_users
                   (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
                   VALUES (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256')""",
                (tenant_a, user_one, user_one, user_one, tenant_a, user_two, user_two, user_two),
            )
            admin.execute(
                """INSERT INTO reconforge.identity_users
                   (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
                   VALUES (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256')""",
                (tenant_b, user_one, user_one, user_one, tenant_b, user_two, user_two, user_two),
            )
            admin.execute(
                """INSERT INTO reconforge.identity_roles(tenant_id,id,name,description)
                   VALUES (%s,%s,%s,'prepare'),(%s,%s,%s,'approve')""",
                (tenant_a, role_prepare, role_prepare, tenant_a, role_approve, role_approve),
            )
            admin.execute(
                """INSERT INTO reconforge.identity_user_roles(tenant_id,user_id,role_id)
                   VALUES (%s,%s,%s),(%s,%s,%s)""",
                (tenant_a, user_one, role_prepare, tenant_a, user_one, role_approve),
            )
            admin.execute(
                """INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
                   VALUES (%s,%s,'close.prepare'),(%s,%s,'close.approve'),(%s,%s,'close.manage')""",
                (tenant_a, role_prepare, tenant_a, role_approve, tenant_a, role_approve),
            )
            admin.execute(
                """INSERT INTO reconforge.service_accounts
                   (tenant_id,id,name,display_name,max_credential_ttl_seconds,created_by)
                   VALUES (%s,%s,%s,%s,3600,%s)""",
                (tenant_a, service_account, service_account, service_account, user_two),
            )
            admin.execute(
                """INSERT INTO reconforge.service_account_permissions
                   (tenant_id,service_account_id,permission_name,granted_by)
                   VALUES (%s,%s,'close.prepare',%s)""",
                (tenant_a, service_account, user_two),
            )

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            result = PolicyAnalysisApplicationService(
                PostgresPolicyAnalysisRepository(connection, tenant_a)
            ).analyze(
                policy_id="postgres-access-policy",
                policy_version="1.0.0",
                require_scoped_privileged=True,
                prepared_by=user_one,
                prepared_at=now,
                approved_by=user_two,
                approved_at=(now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            )
            codes = {finding.code for finding in result.findings}
            assert "sod_permission_overlap" in codes
            assert "unscoped_privileged_grant" in codes

        with PostgresTenantBoundary(app_factory).transaction(tenant_b) as connection:
            sibling = PolicyAnalysisApplicationService(
                PostgresPolicyAnalysisRepository(connection, tenant_b)
            ).analyze(
                policy_id="postgres-access-policy",
                policy_version="1.0.0",
                require_scoped_privileged=True,
                prepared_by=user_one,
                prepared_at=now,
                approved_by=user_two,
                approved_at=(now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            )
            assert sibling.status == "clear"
            assert sibling.active_grant_count == 0
    finally:
        with admin.transaction():
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        admin.close()
