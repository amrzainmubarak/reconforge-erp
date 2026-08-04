from __future__ import annotations

import os
from uuid import uuid4

import pytest

from reconforge.application.intercompany_elimination import IntercompanyEliminationApplicationService
from reconforge.domain.intercompany_elimination import IntercompanyEliminationInputLine
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_intercompany_elimination import (
    PostgresIntercompanyEliminationError,
    PostgresIntercompanyEliminationRepository,
)
from reconforge.utils.money import Money


def _lines(suffix: str) -> tuple[IntercompanyEliminationInputLine, ...]:
    digest_a = ("a" + suffix).ljust(64, "a")[:64]
    digest_b = ("b" + suffix).ljust(64, "b")[:64]
    return (
        IntercompanyEliminationInputLine(
            transaction_id=f"TX-A-{suffix}", period_name="2026-08", entity_code="ENTITY-A",
            counterparty_code="ENTITY-B", reference=f"IC-{suffix}", group_account_code="IC-RECEIVABLE",
            account_type="Asset", amount=Money.from_exact("100.00", "USD", strict_precision=True),
            source_reference=f"ledger:a:{suffix}", source_digest=digest_a,
        ),
        IntercompanyEliminationInputLine(
            transaction_id=f"TX-B-{suffix}", period_name="2026-08", entity_code="ENTITY-B",
            counterparty_code="ENTITY-A", reference=f"IC-{suffix}", group_account_code="IC-PAYABLE",
            account_type="Liability", amount=Money.from_exact("-100.00", "USD", strict_precision=True),
            source_reference=f"ledger:b:{suffix}", source_digest=digest_b,
        ),
    )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_intercompany_elimination_is_replayable_immutable_and_workspace_isolated() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a, tenant_b = f"ice_a_{suffix}", f"ice_b_{suffix}"
    workspace_a = f"ice_ws_a_{suffix}"
    user_a = f"ice_preparer_{suffix}"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                (tenant_a, workspace_a, workspace_a),
            )
            admin.execute(
                f"GRANT USAGE ON SCHEMA reconforge TO {app_user}; "
                f"GRANT SELECT, INSERT ON TABLE reconforge.intercompany_elimination_artifacts, "
                f"reconforge.identity_users, reconforge.domain_workspaces, reconforge.domain_audit_events TO {app_user}; "
                f"GRANT SELECT, INSERT, UPDATE ON TABLE reconforge.domain_audit_ledger_state TO {app_user}"
            )
            admin.execute(
                """INSERT INTO reconforge.identity_users
                   (tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm)
                   VALUES (%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256'),(%s,%s,%s,%s,'x','x',100000,'pbkdf2_sha256')""",
                (tenant_a, user_a, user_a, user_a, tenant_b, user_a, user_a, user_a),
            )
        lines = _lines(suffix)
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service = IntercompanyEliminationApplicationService(
                PostgresIntercompanyEliminationRepository(connection, tenant_a)
            )
            created = service.prepare_and_persist(
                lines,
                reporting_currency="USD",
                prepared_by=user_a,
                prepared_at="2026-08-05T12:00:00Z",
                version="1.0.0",
                workspace=workspace_a,
                actor_label=user_a,
            )
            repeated = service.prepare_and_persist(
                lines,
                reporting_currency="USD",
                prepared_by=user_a,
                prepared_at="2026-08-05T12:00:00Z",
                version="1.0.0",
                workspace=workspace_a,
                actor_label=user_a,
            )
            loaded = service.repository.get(str(created["id"]), actor_label=user_a)  # type: ignore[union-attr]
            assert repeated["id"] == created["id"]
            assert loaded["result_digest"] == created["result_digest"]
            assert loaded["posting"] == "not_available"
        with pytest.raises(PostgresIntercompanyEliminationError, match="not found"), PostgresTenantBoundary(
            app_factory
        ).transaction(tenant_b) as connection:
            PostgresIntercompanyEliminationRepository(connection, tenant_b).get(str(created["id"]), actor_label=user_a)
        with pytest.raises(Exception, match="intercompany elimination artifacts are immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.intercompany_elimination_artifacts SET version='1.0.1' WHERE tenant_id=%s AND id=%s",
                (tenant_a, created["id"]),
            )
        with pytest.raises(Exception, match="intercompany elimination artifacts cannot be deleted"), admin.transaction():
            admin.execute(
                "DELETE FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s AND id=%s",
                (tenant_a, created["id"]),
            )
    finally:
        with admin.transaction():
            admin.execute("ALTER TABLE reconforge.intercompany_elimination_artifacts DISABLE TRIGGER intercompany_elimination_artifact_guard")
            admin.execute("DELETE FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute("ALTER TABLE reconforge.intercompany_elimination_artifacts ENABLE TRIGGER intercompany_elimination_artifact_guard")
            admin.execute("ALTER TABLE reconforge.domain_audit_events DISABLE TRIGGER domain_audit_events_immutable")
            admin.execute("DELETE FROM reconforge.domain_audit_events WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute("ALTER TABLE reconforge.domain_audit_events ENABLE TRIGGER domain_audit_events_immutable")
            admin.execute("DELETE FROM reconforge.identity_users WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute("DELETE FROM reconforge.domain_workspaces WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        admin.close()
