from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from reconforge.api.dependencies import _server_policy_audit_sink
from reconforge.auth.policy import (
    CentralPolicyEngine,
    PolicyDecisionEvidence,
    PolicyEvaluationContext,
    audit_policy_decision,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import (
    PostgresAuditEventRepository,
    install_postgres_domain_schema,
)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_server_policy_provenance_is_redacted_scoped_and_verifiable() -> None:
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")

    pytest.importorskip("psycopg")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "policy_live_a_" + uuid4().hex[:8]
    tenant_b = "policy_live_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.domain_audit_ledger_state, "
                f"reconforge.domain_audit_events TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s), (%s, %s)",
                (tenant_a, "Policy A", tenant_b, "Policy B"),
            )

        app = FastAPI()
        app.state.postgres_identity_factory = app_factory
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/policy",
                "raw_path": b"/api/v1/policy",
                "query_string": b"",
                "headers": [(b"x-reconforge-tenant", tenant_a.encode("ascii"))],
                "app": app,
            }
        )
        context = PolicyEvaluationContext(
            user_id="live-user",
            username="controller",
            user_permissions={"finance_core.validate"},
            tenant_id="tenant-secret",
            workspace_id="workspace-secret",
            amount=Decimal("123456789.01"),
        )
        decision = CentralPolicyEngine().evaluate(context, required_permission="finance_core.validate")
        sink = _server_policy_audit_sink(request, actor_id="live-user")
        assert sink is not None
        evidence = audit_policy_decision(
            decision,
            actor_id="live-user",
            required_permissions=frozenset({"finance_core.validate"}),
            surface="GET /api/v1/policy",
            request_id="request-secret",
            context=context,
            audit_sink=sink,
        )
        assert isinstance(evidence, PolicyDecisionEvidence)

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            repository = PostgresAuditEventRepository(connection, tenant_a)
            events = repository.list()
            verification = repository.verify()
            assert verification.ok is True
            assert len(events) == 1
            event = events[0]
            assert event.object_type == "authorization.policy_decision"
            assert event.object_id == evidence.decision_digest
            assert event.after_hash == evidence.decision_digest
            assert event.metadata["policy_decision_evidence"] == evidence.to_dict()
            serialized = str(event.metadata)
            assert "tenant-secret" not in serialized
            assert "workspace-secret" not in serialized
            assert "123456789.01" not in serialized
            assert "request-secret" not in serialized

        with PostgresTenantBoundary(app_factory).transaction(tenant_b) as connection:
            other_tenant = PostgresAuditEventRepository(connection, tenant_b)
            assert other_tenant.list() == []
            assert other_tenant.verify().ok is True
    finally:
        with admin.transaction():
            admin.execute("ALTER TABLE reconforge.domain_audit_events DISABLE TRIGGER domain_audit_events_immutable")
            try:
                admin.execute(
                    "DELETE FROM reconforge.domain_audit_events WHERE tenant_id IN (%s, %s)",
                    (tenant_a, tenant_b),
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
            finally:
                admin.execute("ALTER TABLE reconforge.domain_audit_events ENABLE TRIGGER domain_audit_events_immutable")
        admin.close()
