from __future__ import annotations

import os
from uuid import uuid4

import pytest

from reconforge.application.consolidation_deferred_tax import AcquisitionDeferredTaxApplicationService
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_consolidation_deferred_tax import (
    PostgresConsolidationDeferredTaxError,
    PostgresConsolidationDeferredTaxRepository,
)
from tests.test_consolidation_deferred_tax import _request


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_deferred_tax_persistence_is_replayable_immutable_and_tenant_isolated() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"dtax_a_{suffix}"
    tenant_b = f"dtax_b_{suffix}"
    user_one = f"dtax_preparer_{suffix}"
    user_two = f"dtax_reviewer_{suffix}"

    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT ON TABLE reconforge.consolidation_deferred_tax_artifacts, "
                f"reconforge.identity_users, reconforge.domain_audit_events TO {app_user}; "
                f"GRANT SELECT, INSERT, UPDATE ON TABLE reconforge.domain_audit_ledger_state TO {app_user}"
            )
            admin.execute(
                """INSERT INTO reconforge.identity_users
                   (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
                   VALUES (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),
                          (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256')""",
                (
                    tenant_a, user_one, user_one, user_one,
                    tenant_a, user_two, user_two, user_two,
                    tenant_b, user_one, user_one, user_one,
                    tenant_b, user_two, user_two, user_two,
                ),
            )

        request = _request(prepared_by=user_one, approved_by=user_two)
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service = AcquisitionDeferredTaxApplicationService(
                PostgresConsolidationDeferredTaxRepository(connection, tenant_a)
            )
            created = service.prepare_and_persist(request, actor_label=user_one)
            repeated = service.prepare_and_persist(request, actor_label=user_one)
            loaded = service.get(str(created["id"]), actor_label=user_one)
            assert repeated["id"] == created["id"]
            assert loaded["result_digest"] == created["result_digest"]
            assert loaded["result_payload"]["posted"] is False

        with pytest.raises(PostgresConsolidationDeferredTaxError, match="not found"), PostgresTenantBoundary(
            app_factory
        ).transaction(tenant_b) as connection:
            AcquisitionDeferredTaxApplicationService(
                PostgresConsolidationDeferredTaxRepository(connection, tenant_b)
            ).get(str(created["id"]), actor_label=user_one)

        with pytest.raises(Exception, match="consolidation deferred-tax artifacts are immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.consolidation_deferred_tax_artifacts SET acquisition_id=%s WHERE tenant_id=%s AND id=%s",
                ("tampered", tenant_a, created["id"]),
            )
        with pytest.raises(Exception, match="consolidation deferred-tax artifacts cannot be deleted"), admin.transaction():
            admin.execute(
                "DELETE FROM reconforge.consolidation_deferred_tax_artifacts WHERE tenant_id=%s AND id=%s",
                (tenant_a, created["id"]),
            )
    finally:
        with admin.transaction():
            admin.execute(
                "ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DISABLE TRIGGER consolidation_deferred_tax_artifact_guard"
            )
            admin.execute(
                "DELETE FROM reconforge.consolidation_deferred_tax_artifacts WHERE tenant_id IN (%s,%s)",
                (tenant_a, tenant_b),
            )
            admin.execute(
                "ALTER TABLE reconforge.consolidation_deferred_tax_artifacts ENABLE TRIGGER consolidation_deferred_tax_artifact_guard"
            )
            admin.execute("ALTER TABLE reconforge.domain_audit_events DISABLE TRIGGER domain_audit_events_immutable")
            admin.execute(
                "DELETE FROM reconforge.domain_audit_events WHERE tenant_id IN (%s,%s)",
                (tenant_a, tenant_b),
            )
            admin.execute("ALTER TABLE reconforge.domain_audit_events ENABLE TRIGGER domain_audit_events_immutable")
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        admin.close()
