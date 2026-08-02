from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from reconforge.auth.delegations import DelegationGrant
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_delegations import PostgresDelegationRepository


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_delegation_is_rls_isolated_and_immutable() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"delegation_a_{suffix}"
    tenant_b = f"delegation_b_{suffix}"
    delegation_id = f"delegation_{suffix}"
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
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE reconforge.policy_delegations TO {app_user}"
            )
        grant = DelegationGrant(
            id=delegation_id,
            tenant_id=tenant_a,
            workspace_id=f"workspace_{suffix}",
            delegator_id=f"manager_{suffix}",
            delegatee_id=f"reviewer_{suffix}",
            permissions=frozenset({"reports.read"}),
            starts_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
            created_by=f"operator_{suffix}",
            approved_by=f"approver_{suffix}",
        )
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            repository = PostgresDelegationRepository(connection)
            assert repository.create(grant) == grant
            assert repository.get_effective(
                delegation_id=delegation_id,
                tenant_id=tenant_a,
                workspace_id=grant.workspace_id,
                evaluation_time=now,
            ) == grant
            assert repository.revoke(
                delegation_id=delegation_id,
                tenant_id=tenant_a,
                workspace_id=grant.workspace_id,
                actor_id=f"security_{suffix}",
                revoked_at=now,
            ).status == "revoked"
            assert repository.get_effective(
                delegation_id=delegation_id,
                tenant_id=tenant_a,
                workspace_id=grant.workspace_id,
                evaluation_time=now,
            ) is None
        with PostgresTenantBoundary(app_factory).transaction(tenant_b) as connection:
            assert PostgresDelegationRepository(connection).get_effective(
                delegation_id=delegation_id,
                tenant_id=tenant_b,
                workspace_id=grant.workspace_id,
                evaluation_time=now,
            ) is None
    finally:
        with admin.transaction():
            admin.execute("DELETE FROM reconforge.policy_delegations WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        admin.close()
