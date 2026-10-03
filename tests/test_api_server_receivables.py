"""Live PostgreSQL HTTP contract for Accounts Receivable and credit controls."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, PrincipalScopeSnapshot
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_receivables import POSTGRES_RECEIVABLES_SCHEMA_SQL
from tests.postgres_test_hygiene import RECEIVABLES_TENANT_CLEANUP_PLAN, cleanup_postgres_test_tenants_as_admin


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_receivables_http_lifecycle_is_scoped_exact_and_human_governed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_id = f"receivables_http_{token}"
    workspace_id = f"workspace_{token}"
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_RECEIVABLES_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,"
                "ar_customers,ar_invoices,ar_invoice_lines,ar_receipts,"
                "ar_receipt_allocations,ar_idempotency_keys"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant_id, tenant_id))

        app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
        with PostgresTenantBoundary(app_factory).transaction(tenant_id) as connection:
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Receivables')",
                (tenant_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                (tenant_id,),
            )
            connection.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'EUR','Euro',2)",
                (tenant_id,),
            )

        maker = LocalUser(id=f"maker-{token}", username=f"maker-{token}", display_name="Maker")
        checker = LocalUser(id=f"checker-{token}", username=f"checker-{token}", display_name="Checker")
        scope = PrincipalScopeSnapshot(workspace_ids=frozenset({workspace_id}))

        def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
            if credential == "maker-token":
                return AuthenticatedServerRequest(
                    user=maker,
                    permissions=frozenset({"receivables.read", "receivables.manage"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            if credential == "checker-token":
                return AuthenticatedServerRequest(
                    user=checker,
                    permissions=frozenset({"receivables.read", "receivables.approve"}),
                    principal_type="user",
                    step_up_active=True,
                    step_up_method="webauthn_user_verified",
                    scope_authority=scope,
                )
            return None

        import reconforge.api.app as app_module
        import reconforge.api.dependencies as dependencies

        monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
        monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
        monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tmp_path / "tenants",
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            base = {
                "X-ReconForge-Tenant": tenant_id,
                "X-ReconForge-Workspace": workspace_id,
            }
            maker_headers = {**base, "Authorization": "Bearer maker-token"}
            checker_headers = {**base, "Authorization": "Bearer checker-token"}

            customer = client.post(
                "/api/v1/receivables/customers",
                headers=maker_headers,
                json={
                    "customer_code": "CUS-HTTP",
                    "name": "HTTP Customer",
                    "currency_code": "USD",
                    "credit_limit_minor": 10_000,
                    "workspace": "spoofed-workspace",
                },
            )
            assert customer.status_code == 200, customer.text

            invoice = client.post(
                "/api/v1/receivables/invoices",
                headers=maker_headers,
                json={
                    "invoice_number": "INV-HTTP-1",
                    "customer_code": "CUS-HTTP",
                    "invoice_date": "2026-07-01",
                    "currency_code": "USD",
                    "workspace": "spoofed-workspace",
                    "lines": [
                        {
                            "description": "Exact quantity",
                            "quantity": "1.0000000000001",
                            "unit_price_minor": 100,
                            "line_total_minor": 100,
                        }
                    ],
                },
            )
            assert invoice.status_code == 200, invoice.text
            invoice_body = invoice.json()
            invoice_id = str(invoice_body["id"])
            assert invoice_body["lines"][0]["quantity"] == "1.0000000000001"
            assert invoice_body["created_by"] == maker.id

            maker_approval = client.post(
                f"/api/v1/receivables/invoices/{invoice_id}/approve",
                headers=maker_headers,
                json={"expected_version": 2},
            )
            assert maker_approval.status_code == 403

            submitted = client.post(
                f"/api/v1/receivables/invoices/{invoice_id}/submit",
                headers=maker_headers,
                json={"expected_version": 1},
            )
            assert submitted.status_code == 200, submitted.text

            profile = {"customer_code": "CUS-HTTP", "name": "HTTP Customer", "currency_code": "USD", "credit_limit_minor": 10_000}
            changed_currency = client.post("/api/v1/receivables/customers", headers=maker_headers, json={**profile, "currency_code": "EUR"})
            assert changed_currency.status_code == 400, changed_currency.text
            suspended = client.post("/api/v1/receivables/customers", headers=maker_headers, json={**profile, "status": "Suspended"})
            assert suspended.status_code == 200, suspended.text
            blocked = client.post(f"/api/v1/receivables/invoices/{invoice_id}/approve", headers=checker_headers, json={"expected_version": 2})
            assert blocked.status_code == 400, blocked.text
            restored = client.post("/api/v1/receivables/customers", headers=maker_headers, json=profile)
            assert restored.status_code == 200, restored.text

            approved = client.post(
                f"/api/v1/receivables/invoices/{invoice_id}/approve",
                headers=checker_headers,
                json={"expected_version": 2},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "Approved"
            assert approved.json()["approved_by"] == checker.id

            receipt = client.post(
                "/api/v1/receivables/receipts",
                headers=maker_headers,
                json={
                    "receipt_number": "RCT-HTTP-1",
                    "customer_code": "CUS-HTTP",
                    "receipt_date": "2026-07-28",
                    "currency_code": "USD",
                    "amount_minor": 40,
                    "workspace": "spoofed-workspace",
                    "allocations": [{"invoice_id": invoice_id, "amount_minor": 40}],
                },
            )
            assert receipt.status_code == 200, receipt.text
            assert receipt.json()["unallocated_minor"] == 0

            exposure = client.get(
                "/api/v1/receivables/credit-exposure/CUS-HTTP",
                headers=checker_headers,
            )
            aging = client.get(
                "/api/v1/receivables/aging",
                headers=checker_headers,
                params={"as_of_date": "2026-07-28", "workspace": "spoofed-workspace"},
            )
            invoices = client.get(
                "/api/v1/receivables/invoices",
                headers=checker_headers,
                params={"workspace": "spoofed-workspace"},
            )
            denied_workspace = client.get(
                "/api/v1/receivables/customers",
                headers={**checker_headers, "X-ReconForge-Workspace": "workspace-not-granted"},
            )

            assert exposure.status_code == 200, exposure.text
            assert exposure.json()["exposure_minor"] == 60
            assert exposure.json()["available_credit_minor"] == 9_940
            assert aging.status_code == 200, aging.text
            assert aging.json()["total_outstanding_minor"] == 60
            assert all("organization_id" not in item for item in aging.json()["items"])
            assert invoices.status_code == 200, invoices.text
            assert invoices.json()["pagination"]["total"] == 1
            assert denied_workspace.status_code == 403
            assert denied_workspace.json()["error"]["code"] == "workspace_scope_denied"

            assert aging.json()["currency_code"] == "USD"
            euro_customer = client.post("/api/v1/receivables/customers", headers=maker_headers, json={
                "customer_code": "CUS-EUR", "name": "Synthetic EUR Customer", "currency_code": "EUR", "credit_limit_minor": 10000,
            })
            assert euro_customer.status_code == 200, euro_customer.text
            euro_invoice = client.post("/api/v1/receivables/invoices", headers=maker_headers, json={
                "invoice_number": "INV-EUR", "customer_code": "CUS-EUR", "invoice_date": "2026-07-01", "currency_code": "EUR",
                "lines": [{"description": "Synthetic EUR", "quantity": "1", "unit_price_minor": 300, "line_total_minor": 300}],
            })
            assert euro_invoice.status_code == 200, euro_invoice.text
            euro_id = euro_invoice.json()["id"]
            assert client.post(f"/api/v1/receivables/invoices/{euro_id}/submit", headers=maker_headers, json={"expected_version": 1}).status_code == 200
            assert client.post(f"/api/v1/receivables/invoices/{euro_id}/approve", headers=checker_headers, json={"expected_version": 2}).status_code == 200
            assert client.get("/api/v1/receivables/aging?as_of_date=2026-07-28", headers=checker_headers).status_code == 400
            grouped = client.get("/api/v1/receivables/aging-by-currency?as_of_date=2026-07-28", headers=checker_headers)
            assert grouped.status_code == 200, grouped.text
            assert [(group["currency_code"], group["total_outstanding_minor"]) for group in grouped.json()["currency_groups"]] == [("EUR", 300), ("USD", 60)]
            assert all("organization_id" not in item for group in grouped.json()["currency_groups"] for item in group["items"])
            assert client.get("/api/v1/receivables/aging-by-currency?as_of_date=2026-07-28", headers={**checker_headers, "X-ReconForge-Workspace": "workspace-not-granted"}).status_code == 403
    finally:
        try:
            cleanup_postgres_test_tenants_as_admin(admin, tenant_ids=(tenant_id,), plan=RECEIVABLES_TENANT_CLEANUP_PLAN)
        finally:
            admin.close()
