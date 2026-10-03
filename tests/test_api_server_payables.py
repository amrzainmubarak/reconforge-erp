"""Live PostgreSQL HTTP contract for Accounts Payable and three-way matching."""

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
from reconforge.infrastructure.postgres_journals import POSTGRES_JOURNAL_SCHEMA_SQL
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_payables import POSTGRES_PAYABLES_SCHEMA_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_payables_http_lifecycle_is_scoped_exact_and_human_governed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_id = f"payables_http_{token}"
    workspace_id = f"workspace_{token}"
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_JOURNAL_SCHEMA_SQL)
            admin.execute(POSTGRES_PAYABLES_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,branches,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,control_exceptions,"
                "ap_suppliers,ap_purchase_orders,ap_purchase_order_lines,ap_goods_receipts,"
                "ap_goods_receipt_lines,ap_supplier_invoices,ap_supplier_invoice_lines,"
                "ap_three_way_matches,ap_idempotency_keys"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant_id, tenant_id))

        app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
        with PostgresTenantBoundary(app_factory).transaction(tenant_id) as connection:
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Payables')",
                (tenant_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                (tenant_id,),
            )

        maker = LocalUser(id=f"maker-{token}", username=f"maker-{token}", display_name="Maker")
        checker = LocalUser(id=f"checker-{token}", username=f"checker-{token}", display_name="Checker")
        matcher = LocalUser(id=f"matcher-{token}", username=f"matcher-{token}", display_name="Matcher")
        scope = PrincipalScopeSnapshot(workspace_ids=frozenset({workspace_id}))

        def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
            if credential == "maker-token":
                return AuthenticatedServerRequest(
                    user=maker,
                    permissions=frozenset({"payables.read", "payables.manage"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            if credential == "checker-token":
                return AuthenticatedServerRequest(
                    user=checker,
                    permissions=frozenset({"payables.read", "payables.approve"}),
                    principal_type="user",
                    step_up_active=True,
                    step_up_method="webauthn_user_verified",
                    scope_authority=scope,
                )
            if credential == "matcher-token":
                return AuthenticatedServerRequest(
                    user=matcher,
                    permissions=frozenset({"payables.read", "payables.match"}),
                    principal_type="user",
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
            base = {"X-ReconForge-Tenant": tenant_id, "X-ReconForge-Workspace": workspace_id}
            maker_headers = {**base, "Authorization": "Bearer maker-token"}
            checker_headers = {**base, "Authorization": "Bearer checker-token"}
            matcher_headers = {**base, "Authorization": "Bearer matcher-token"}

            supplier = client.post(
                "/api/v1/payables/suppliers",
                headers=maker_headers,
                json={
                    "supplier_code": "SUP-HTTP",
                    "name": "HTTP Supplier",
                    "currency_code": "USD",
                    "workspace": "spoofed-workspace",
                },
            )
            assert supplier.status_code == 200, supplier.text

            order = client.post(
                "/api/v1/payables/purchase-orders",
                headers=maker_headers,
                json={
                    "po_number": "PO-HTTP-1",
                    "supplier_code": "SUP-HTTP",
                    "order_date": "2026-07-28",
                    "currency_code": "USD",
                    "workspace": "spoofed-workspace",
                    "lines": [
                        {
                            "item_code": "ITEM-HTTP",
                            "ordered_quantity": "1.0000000000001",
                            "unit_price_minor": 100,
                        }
                    ],
                },
            )
            assert order.status_code == 200, order.text
            order_body = order.json()
            order_id = str(order_body["id"])
            line_id = str(order_body["lines"][0]["id"])
            assert order_body["created_by"] == maker.id
            assert order_body["lines"][0]["ordered_quantity"] == "1.0000000000001"

            maker_approval = client.post(
                f"/api/v1/payables/purchase-orders/{order_id}/approve",
                headers=maker_headers,
                json={"expected_version": 2},
            )
            assert maker_approval.status_code == 403
            submitted_order = client.post(
                f"/api/v1/payables/purchase-orders/{order_id}/submit",
                headers=maker_headers,
                json={"expected_version": 1},
            )
            assert submitted_order.status_code == 200, submitted_order.text
            approved_order = client.post(
                f"/api/v1/payables/purchase-orders/{order_id}/approve",
                headers=checker_headers,
                json={"expected_version": 2},
            )
            assert approved_order.status_code == 200, approved_order.text
            assert approved_order.json()["approved_by"] == checker.id

            receipt = client.post(
                "/api/v1/payables/receipts",
                headers=maker_headers,
                json={
                    "receipt_number": "GR-HTTP-1",
                    "purchase_order_id": order_id,
                    "receipt_date": "2026-07-28",
                    "quantities": {line_id: "1.0000000000001"},
                    "workspace": "spoofed-workspace",
                },
            )
            assert receipt.status_code == 200, receipt.text

            invoice = client.post(
                "/api/v1/payables/invoices",
                headers=maker_headers,
                json={
                    "invoice_number": "INV-HTTP-1",
                    "supplier_code": "SUP-HTTP",
                    "invoice_date": "2026-07-28",
                    "currency_code": "USD",
                    "total_minor": 100,
                    "purchase_order_id": order_id,
                    "workspace": "spoofed-workspace",
                    "lines": [
                        {
                            "purchase_order_line_id": line_id,
                            "invoiced_quantity": "1.0000000000001",
                            "unit_price_minor": 100,
                            "line_total_minor": 100,
                        }
                    ],
                },
            )
            assert invoice.status_code == 200, invoice.text
            invoice_id = str(invoice.json()["id"])
            submitted_invoice = client.post(
                f"/api/v1/payables/invoices/{invoice_id}/submit",
                headers=maker_headers,
                json={"expected_version": 1},
            )
            assert submitted_invoice.status_code == 200, submitted_invoice.text
            matched = client.post(f"/api/v1/payables/invoices/{invoice_id}/match", headers=matcher_headers)
            assert matched.status_code == 200, matched.text
            assert matched.json()["status"] == "Passed"
            approved_invoice = client.post(
                f"/api/v1/payables/invoices/{invoice_id}/approve",
                headers=checker_headers,
                json={"expected_version": 3},
            )
            assert approved_invoice.status_code == 200, approved_invoice.text
            assert approved_invoice.json()["approved_by"] == checker.id

            suppliers = client.get("/api/v1/payables/suppliers", headers=checker_headers, params={"workspace": "spoofed-workspace"})
            invoices = client.get("/api/v1/payables/invoices", headers=checker_headers, params={"workspace": "spoofed-workspace"})
            denied_workspace = client.get(
                "/api/v1/payables/suppliers",
                headers={**checker_headers, "X-ReconForge-Workspace": "workspace-not-granted"},
            )
            assert suppliers.status_code == 200, suppliers.text
            assert suppliers.json()["pagination"]["total"] == 1
            assert invoices.status_code == 200, invoices.text
            assert invoices.json()["pagination"]["total"] == 1
            assert denied_workspace.status_code == 403
            assert denied_workspace.json()["error"]["code"] == "workspace_scope_denied"
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant_id,))
        except psycopg.Error:
            pass
        finally:
            admin.close()
