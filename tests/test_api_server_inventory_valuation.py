"""Live PostgreSQL HTTP contracts for Inventory Valuation and Reversals."""

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
from reconforge.infrastructure.postgres_finance_core import install_postgres_finance_core_schema
from reconforge.infrastructure.postgres_inventory_core import (
    POSTGRES_INVENTORY_CORE_SCHEMA_SQL,
    PostgresInventoryCoreRepository,
)
from reconforge.infrastructure.postgres_inventory_valuation import POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_master_data_application import install_postgres_master_data_application_schema


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_inventory_valuation_and_reversal_http_contract_is_exact_and_scoped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_id = f"valuation_http_{token}"
    workspace_id = f"workspace_{token}"
    organization_id = f"org_{token}"
    entity_id = f"entity_{token}"
    period_id = f"period_{token}"
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_FISCAL_PERIOD_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            install_postgres_master_data_application_schema(admin)
            install_postgres_finance_core_schema(admin)
            admin.execute(POSTGRES_INVENTORY_CORE_SCHEMA_SQL)
            admin.execute(POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL)
            admin.execute(POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant_id, tenant_id))

        factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Inventory')",
                (tenant_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                (tenant_id,),
            )
            connection.execute(
                "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,active,application_workspace_id) VALUES (%s,%s,'ORG','Organization','USD',TRUE,%s)",
                (tenant_id, organization_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES (%s,%s,%s)",
                (tenant_id, workspace_id, organization_id),
            )
            connection.execute(
                "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES (%s,%s,%s,'ENTITY','Entity','USD')",
                (tenant_id, entity_id, organization_id),
            )
            connection.execute(
                "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES (%s,%s,'2026-07','2026-07-01','2026-07-31',2026,7,%s)",
                (tenant_id, period_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES (%s,%s,%s)",
                (tenant_id, workspace_id, period_id),
            )
            from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository

            finance = PostgresFinanceCoreRepository(connection, tenant_id)
            finance.upsert_chart(chart_code="DEFAULT", name="Default", workspace=workspace_id, organization_code="ORG")
            for account_code, name, account_type in (
                ("INVENTORY", "Inventory", "Asset"),
                ("CLEARING", "Receipt clearing", "Liability"),
                ("COGS", "Cost of goods sold", "Expense"),
                ("ADJUSTMENT", "Inventory adjustment", "Expense"),
            ):
                finance.upsert_account(
                    account_code=account_code,
                    name=name,
                    workspace=workspace_id,
                    chart_code="DEFAULT",
                    account_type=account_type,
                )
            finance.upsert_journal(
                journal_code="INVENTORY",
                name="Inventory valuation",
                organization_code="ORG",
                currency_code="USD",
                workspace=workspace_id,
            )
            inventory = PostgresInventoryCoreRepository(connection, tenant_id)
            inventory.upsert_uom(uom_code="KG", name="Kilogram", category="Weight", decimal_places=3, workspace=workspace_id)
            inventory.upsert_item(
                item_code="MATERIAL",
                name="Material",
                organization_code="ORG",
                uom_code="KG",
                inventory_account_code="INVENTORY",
                workspace=workspace_id,
            )
            inventory.upsert_warehouse(
                warehouse_code="MAIN", name="Main", organization_code="ORG", entity_code="ENTITY", workspace=workspace_id
            )
            inventory.upsert_location(
                warehouse_code="MAIN", location_code="STOCK", name="Stock", organization_code="ORG", workspace=workspace_id
            )
            receipt = inventory.create_movement(
                movement_number="RCPT-HTTP-1",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=period_id,
                movement_date="2026-07-27",
                description="Synthetic HTTP valuation receipt",
                lines=[{"item_code": "MATERIAL", "quantity": "2.500", "to_location": "MAIN/STOCK"}],
                workspace=workspace_id,
                actor_label="seed-maker",
            )
            inventory.post_movement(str(receipt["id"]), reason="Seed review", actor_label="seed-checker")

        maker = LocalUser(id=f"maker-{token}", username=f"maker-{token}", display_name="Maker")
        checker = LocalUser(id=f"checker-{token}", username=f"checker-{token}", display_name="Checker")
        scope = PrincipalScopeSnapshot(
            workspace_ids=frozenset({workspace_id}),
            organization_ids=frozenset({organization_id}),
            legal_entity_ids=frozenset({entity_id}),
        )

        def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
            if credential == "maker-token":
                return AuthenticatedServerRequest(
                    user=maker,
                    permissions=frozenset({"inventory.read", "inventory.valuation.manage", "inventory.valuation.reverse.manage"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            if credential == "checker-token":
                return AuthenticatedServerRequest(
                    user=checker,
                    permissions=frozenset({"inventory.read", "inventory.valuation.approve", "inventory.valuation.reverse.approve"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            return None

        import reconforge.api.app as app_module
        import reconforge.api.dependencies as dependencies

        monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
        monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
        monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)

        app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=dsn, postgres_require_tls=False)
        with TestClient(app) as client:
            base = {
                "X-ReconForge-Tenant": tenant_id,
                "X-ReconForge-Workspace": workspace_id,
                "X-ReconForge-Organization": organization_id,
                "X-ReconForge-Legal-Entity": entity_id,
            }
            maker_headers = {**base, "Authorization": "Bearer maker-token"}
            checker_headers = {**base, "Authorization": "Bearer checker-token"}
            policy = client.post(
                "/api/v1/inventory-valuation/policies",
                headers=maker_headers,
                json={
                    "policy_code": "FIFO",
                    "organization_code": "ORG",
                    "entity_code": "ENTITY",
                    "journal_code": "INVENTORY",
                    "receipt_clearing_account_code": "CLEARING",
                    "cogs_account_code": "COGS",
                    "adjustment_account_code": "ADJUSTMENT",
                    "workspace": "spoofed-workspace",
                },
            )
            assert policy.status_code == 200, policy.text
            receipt_document = client.post(
                "/api/v1/inventory-valuation/documents",
                headers=maker_headers,
                json={
                    "valuation_number": "VAL-HTTP-RECEIPT",
                    "movement_id": str(receipt["id"]),
                    "policy_code": "FIFO",
                    "input_costs": [{"line_number": 1, "total_cost": "12.34"}],
                },
            )
            assert receipt_document.status_code == 200, receipt_document.text
            receipt_document_id = str(receipt_document.json()["document"]["id"])
            self_approval = client.post(
                f"/api/v1/inventory-valuation/documents/{receipt_document_id}/approve",
                headers=maker_headers,
                json={"reason": "Self approval"},
            )
            assert self_approval.status_code == 403
            receipt_approved = client.post(
                f"/api/v1/inventory-valuation/documents/{receipt_document_id}/approve",
                headers=checker_headers,
                json={"reason": "Independent approval"},
            )
            assert receipt_approved.status_code == 200, receipt_approved.text
            assert receipt_approved.json()["document"]["total_value"] == "12.34"

        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            inventory = PostgresInventoryCoreRepository(connection, tenant_id)
            delivery = inventory.create_movement(
                movement_number="SHIP-HTTP-1",
                movement_type="Delivery",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=period_id,
                movement_date="2026-07-28",
                description="Synthetic HTTP valuation delivery",
                lines=[{"item_code": "MATERIAL", "quantity": "1.000", "from_location": "MAIN/STOCK"}],
                workspace=workspace_id,
                actor_label="seed-maker",
            )
            inventory.post_movement(str(delivery["id"]), reason="Seed review", actor_label="seed-checker")
            reversal_movement = inventory.create_movement(
                movement_number="RCPT-HTTP-REVERSAL",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=period_id,
                movement_date="2026-07-29",
                description="Synthetic compensating receipt",
                lines=[{"item_code": "MATERIAL", "quantity": "1.000", "to_location": "MAIN/STOCK"}],
                workspace=workspace_id,
                actor_label="seed-maker",
            )
            inventory.post_movement(str(reversal_movement["id"]), reason="Seed review", actor_label="seed-checker")

        app = create_api_app(
            tmp_path / "unused-second.db",
            tenant_db_root=tmp_path / "tenants-second",
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            issue_document = client.post(
                "/api/v1/inventory-valuation/documents",
                headers=maker_headers,
                json={
                    "valuation_number": "VAL-HTTP-DELIVERY",
                    "movement_id": str(delivery["id"]),
                    "policy_code": "FIFO",
                },
            )
            assert issue_document.status_code == 200, issue_document.text
            issue_document_id = str(issue_document.json()["document"]["id"])
            issue_approved = client.post(
                f"/api/v1/inventory-valuation/documents/{issue_document_id}/approve",
                headers=checker_headers,
                json={"reason": "Independent delivery valuation"},
            )
            assert issue_approved.status_code == 200, issue_approved.text
            assert issue_approved.json()["document"]["total_value"] == "4.94"
            reversal = client.post(
                "/api/v1/inventory-valuation/reversals",
                headers=maker_headers,
                json={
                    "reversal_number": "REV-HTTP-DELIVERY",
                    "original_valuation_document_id": issue_document_id,
                    "reversal_movement_id": str(reversal_movement["id"]),
                },
            )
            assert reversal.status_code == 200, reversal.text
            reversal_id = str(reversal.json()["reversal"]["id"])
            reversal_self_approval = client.post(
                f"/api/v1/inventory-valuation/reversals/{reversal_id}/approve",
                headers=maker_headers,
                json={"reason": "Self approval"},
            )
            assert reversal_self_approval.status_code == 403
            reversal_approved = client.post(
                f"/api/v1/inventory-valuation/reversals/{reversal_id}/approve",
                headers=checker_headers,
                json={"reason": "Independent reversal approval"},
            )
            assert reversal_approved.status_code == 200, reversal_approved.text
            assert reversal_approved.json()["reversal"]["status"] == "Approved"
            snapshot = client.get("/api/v1/inventory-valuation/snapshot", headers=checker_headers)
            assert snapshot.status_code == 200, snapshot.text
            assert snapshot.json()["summary"]["approved_documents"] == 2
            denied = client.get(
                "/api/v1/inventory-valuation/summary",
                headers={**checker_headers, "X-ReconForge-Workspace": "workspace-not-granted"},
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "workspace_scope_denied"
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant_id,))
        except psycopg.Error:
            pass
        finally:
            admin.close()
