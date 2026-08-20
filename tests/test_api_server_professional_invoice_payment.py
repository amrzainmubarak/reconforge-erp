from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.errors import APIError
from reconforge.api.routes import professional_invoice_payment
from reconforge.application.professional_invoice_payment_control import (
    run_professional_invoice_payment_control_files,
    verify_professional_invoice_payment_report,
    write_professional_invoice_payment_report,
)
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_professional_invoice_payment import (
    POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL,
    PostgresProfessionalInvoicePaymentRepository,
)
from reconforge.infrastructure.postgres_scope_authority import (
    POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL,
    PostgresScopeAuthorityRepository,
)
from reconforge.infrastructure.postgres_service_accounts import (
    POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
    PostgresServiceAccountRepository,
)
from reconforge.platform.common import ServerPrincipal

ROOT = Path(__file__).resolve().parents[1]


def _request(*, workspace_id: str | None = "workspace-a") -> Request:
    app = FastAPI()
    factory = PostgresConnectionFactory(PostgresSettings(dsn="postgresql://professional.test/postgres", require_tls=False))
    app.state.postgres_identity_factory = factory
    app.state.postgres_professional_invoice_payment_factory = factory
    headers = [(b"x-reconforge-tenant", b"tenant-a")]
    if workspace_id is not None:
        headers.extend(
            [
                (b"x-reconforge-workspace", workspace_id.encode("ascii")),
                (b"x-reconforge-organization", b"organization-a"),
                (b"x-reconforge-legal-entity", b"entity-a"),
            ]
        )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "app": app})
    request.state.server_principal = ServerPrincipal(
        user=LocalUser(id="user-a", username="alice", display_name="Alice"),
        permissions=frozenset({"finance_core.manage", "finance_core.read"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
        authorized_organization_ids=frozenset({"organization-a"}),
        authorized_legal_entity_ids=frozenset({"entity-a"}),
    )
    return request


def test_server_professional_route_does_not_fallback_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    captured: dict[str, object] = {}

    def fake_execute(request: Request, operation: Callable[[object, str, str], object]) -> object:
        class Repository:
            def put_payload(
                self,
                report: dict[str, object],
                *,
                tenant_id: str,
                workspace_id: str,
                actor_label: str,
            ) -> dict[str, object]:
                captured.update(
                    report=report,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    actor_label=actor_label,
                )
                return {"id": "pip-server", "workspace_id": workspace_id, "report": report}

        return operation(Repository(), "tenant-a", "workspace-a")

    monkeypatch.setattr(professional_invoice_payment, "execute_postgres_professional_invoice_payment", fake_execute)
    monkeypatch.setattr(professional_invoice_payment, "enforce_server_scoped_permission", lambda *args, **kwargs: None)
    result = professional_invoice_payment.persist_professional_invoice_payment(
        request,
        professional_invoice_payment.ProfessionalInvoicePaymentPersistenceRequest(
            report={"decision_digest": "f" * 64, "artifact_digest": "a" * 64},
            workspace="workspace-a",
        ),
        request.state.server_principal.user,
        None,
    )
    assert result["source"] == {"kind": "postgresql-professional-invoice-payment", "server_mode": True}
    assert result["network_dispatch"] == "disabled"
    assert captured == {
        "report": {"decision_digest": "f" * 64, "artifact_digest": "a" * 64},
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "actor_label": "alice",
    }


def test_server_professional_route_rejects_missing_workspace_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(workspace_id=None)
    monkeypatch.setattr(professional_invoice_payment, "enforce_server_scoped_permission", lambda *args, **kwargs: None)
    with pytest.raises(APIError, match="Workspace"):
        professional_invoice_payment.persist_professional_invoice_payment(
            request,
            professional_invoice_payment.ProfessionalInvoicePaymentPersistenceRequest(
                report={"decision_digest": "f" * 64, "artifact_digest": "a" * 64},
                workspace="workspace-a",
            ),
            request.state.server_principal.user,
            None,
        )


def _live_professional_report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "professional-http-report.json"
    run = run_professional_invoice_payment_control_files(
        ROOT / "examples/professional_invoice_payment/invoices.json",
        ROOT / "examples/professional_invoice_payment/payments.json",
        currency="USD",
        tolerance="0.01",
    )
    write_professional_invoice_payment_report(run, report_path)
    return verify_professional_invoice_payment_report(report_path)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_professional_invoice_payment_http_routes_are_rls_scoped(tmp_path: Path) -> None:
    """Exercise real service-account auth, server selection, and tenant/workspace RLS."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    tenant_a = "pip_http_a_" + uuid4().hex[:8]
    tenant_b = "pip_http_b_" + uuid4().hex[:8]
    workspace = "professional-http-workspace"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    report = _live_professional_report(tmp_path)
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = None
    try:
        admin = admin_factory.connect()
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
            admin.execute(POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.tenants, reconforge.identity_permissions, "
                f"reconforge.service_accounts, reconforge.service_account_permissions, "
                f"reconforge.service_account_credentials, reconforge.service_account_events TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT ON reconforge.principal_scope_grants, "
                f"reconforge.professional_invoice_payment_runs TO {app_user}"
            )
            admin.execute(f"GRANT SELECT ON reconforge.domain_workspaces TO {app_user}")
            admin.execute(
                f"GRANT SELECT ON reconforge.organizations, reconforge.currencies, "
                f"reconforge.legal_entities TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, workspace, "Professional HTTP workspace"),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) "
                "VALUES (%s,'finance_core.read','Professional evidence read')",
                (tenant_a,),
            )

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service_accounts = PostgresServiceAccountRepository(connection)
            service_accounts.create_account(
                tenant_id=tenant_a,
                account_id="svc-professional-http",
                name="professional-http",
                display_name="Professional HTTP reader",
                permissions=frozenset({"finance_core.read"}),
                actor_id="security-admin",
            )
            credential = service_accounts.issue_credential(
                tenant_id=tenant_a,
                account_id="svc-professional-http",
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=tenant_a,
                grant_id="grant-professional-http-workspace",
                principal_type="service_account",
                principal_id="svc-professional-http",
                scope_type="workspace",
                scope_id=workspace,
                actor_id="security-admin",
            )
            PostgresProfessionalInvoicePaymentRepository(connection).put_payload(
                report,
                tenant_id=tenant_a,
                workspace_id=workspace,
                actor_label="server-fixture",
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            headers = {
                "X-ReconForge-Tenant": tenant_a,
                "X-ReconForge-Workspace": workspace,
                "Authorization": f"Bearer {credential.token}",
            }
            listed = client.get("/api/v1/professional/invoice-payments", headers=headers)
            assert listed.status_code == 200, listed.text
            listed_payload = listed.json()
            assert listed_payload["source"] == {
                "kind": "postgresql-professional-invoice-payment",
                "server_mode": True,
            }
            assert listed_payload["workspace"] == workspace
            assert [item["decision_digest"] for item in listed_payload["invoice_payments"]] == [
                report["decision_digest"]
            ]

            decision_digest = str(report["decision_digest"])
            read = client.get(f"/api/v1/professional/invoice-payments/{decision_digest}", headers=headers)
            assert read.status_code == 200, read.text
            assert read.json()["invoice_payment"]["report"]["artifact_digest"] == report["artifact_digest"]

            denied_workspace = client.get(
                "/api/v1/professional/invoice-payments",
                params={"workspace": "other-workspace"},
                headers=headers,
            )
            assert denied_workspace.status_code == 403

            cross_tenant = client.get(
                "/api/v1/professional/invoice-payments",
                headers={
                    "X-ReconForge-Tenant": tenant_b,
                    "X-ReconForge-Workspace": workspace,
                    "Authorization": f"Bearer {credential.token}",
                },
            )
            assert cross_tenant.status_code == 401
    finally:
        if admin is not None:
            try:
                with admin.transaction():
                    admin.execute(
                        "ALTER TABLE reconforge.professional_invoice_payment_runs "
                        "DISABLE TRIGGER professional_invoice_payment_runs_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.principal_scope_grants "
                        "DISABLE TRIGGER principal_scope_grants_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.service_account_events "
                        "DISABLE TRIGGER trg_service_account_events_append_only"
                    )
                    for table in (
                        "professional_invoice_payment_runs",
                        "principal_scope_grants",
                        "service_account_events",
                        "service_account_credentials",
                        "service_account_permissions",
                        "service_accounts",
                        "identity_permissions",
                        "domain_workspaces",
                    ):
                        admin.execute(
                            f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s, %s)",
                            (tenant_a, tenant_b),
                        )
                    admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
                    admin.execute(
                        "ALTER TABLE reconforge.professional_invoice_payment_runs "
                        "ENABLE TRIGGER professional_invoice_payment_runs_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.principal_scope_grants "
                        "ENABLE TRIGGER principal_scope_grants_guard"
                    )
                    admin.execute(
                        "ALTER TABLE reconforge.service_account_events "
                        "ENABLE TRIGGER trg_service_account_events_append_only"
                    )
            finally:
                admin.close()
