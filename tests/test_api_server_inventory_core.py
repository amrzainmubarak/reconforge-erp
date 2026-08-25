"""Live PostgreSQL HTTP contract for Inventory Core."""

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
from reconforge.infrastructure.postgres_inventory_core import POSTGRES_INVENTORY_CORE_SCHEMA_SQL
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_master_data_application import (
    install_postgres_master_data_application_schema,
)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_inventory_http_lifecycle_is_scoped_and_exact(tmp_path: Path, monkeypatch: Any) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_id = f"inventory_http_{token}"
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
            install_postgres_master_data_application_schema(admin)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            install_postgres_finance_core_schema(admin)
            admin.execute(POSTGRES_INVENTORY_CORE_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)",
                (tenant_id, tenant_id),
            )
        app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
        with PostgresTenantBoundary(app_factory).transaction(tenant_id) as connection:
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Inventory')",
                (tenant_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                (tenant_id,),
            )
            connection.execute(
                "INSERT INTO reconforge.organizations(tenant_id,id,application_workspace_id,organization_code,name,base_currency,active) "
                "VALUES (%s,%s,%s,'ORG','Organization','USD',TRUE)",
                (tenant_id, organization_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) "
                "VALUES (%s,%s,%s)",
                (tenant_id, workspace_id, organization_id),
            )
            connection.execute(
                "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) "
                "VALUES (%s,%s,%s,'ENTITY','Entity','USD')",
                (tenant_id, entity_id, organization_id),
            )
            connection.execute(
                "INSERT INTO reconforge.fiscal_periods(tenant_id,id,application_workspace_id,name,start_date,end_date,fiscal_year,period_number) "
                "VALUES (%s,%s,%s,'2026-07','2026-07-01','2026-07-31',2026,7)",
                (tenant_id, period_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) "
                "VALUES (%s,%s,%s)",
                (tenant_id, workspace_id, period_id),
            )
        with PostgresTenantBoundary(app_factory).transaction(tenant_id) as connection:
            hierarchy_rows = connection.execute(
                "SELECT o.id,o.organization_code,l.workspace_id FROM reconforge.organizations o "
                "JOIN reconforge.master_data_workspace_organizations l ON l.tenant_id=o.tenant_id "
                "AND l.organization_id=o.id WHERE o.tenant_id=%s",
                (tenant_id,),
            ).fetchall()
            assert hierarchy_rows, (tenant_id, organization_id, workspace_id)

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
                    permissions=frozenset({"inventory.read", "inventory.manage"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            if credential == "checker-token":
                return AuthenticatedServerRequest(
                    user=checker,
                    permissions=frozenset({"inventory.read", "inventory.post"}),
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
                "X-ReconForge-Organization": organization_id,
                "X-ReconForge-Legal-Entity": entity_id,
            }
            maker_headers = {**base, "Authorization": "Bearer maker-token"}
            checker_headers = {**base, "Authorization": "Bearer checker-token"}

            unit = client.post(
                "/api/v1/inventory/units",
                headers=maker_headers,
                json={"uom_code": "KG", "name": "Kilogram", "category": "Weight", "decimal_places": 3,
                      "workspace": "spoofed-workspace"},
            )
            item = client.post(
                "/api/v1/inventory/items",
                headers=maker_headers,
                json={"item_code": "MATERIAL", "name": "Material", "organization_code": "ORG",
                      "uom_code": "KG", "workspace": "spoofed-workspace"},
            )
            warehouse = client.post(
                "/api/v1/inventory/warehouses",
                headers=maker_headers,
                json={"warehouse_code": "MAIN", "name": "Main", "organization_code": "ORG",
                      "entity_code": "ENTITY", "workspace": "spoofed-workspace"},
            )
            location = client.post(
                "/api/v1/inventory/locations",
                headers=maker_headers,
                json={"warehouse_code": "MAIN", "location_code": "STOCK", "name": "Stock",
                      "organization_code": "ORG", "workspace": "spoofed-workspace"},
            )
            assert unit.status_code == 200, unit.text
            assert item.status_code == 200, item.text
            assert warehouse.status_code == 200, warehouse.text
            assert location.status_code == 200, location.text
            movement = client.post(
                "/api/v1/inventory/movements",
                headers=maker_headers,
                json={
                    "movement_number": "RCPT-HTTP-1",
                    "movement_type": "Receipt",
                    "organization_code": "ORG",
                    "entity_code": "ENTITY",
                    "period_id": period_id,
                    "movement_date": "2026-07-28",
                    "description": "Synthetic HTTP receipt",
                    "workspace": "spoofed-workspace",
                    "lines": [{"item_code": "MATERIAL", "quantity": "2.500", "to_location": "MAIN/STOCK"}],
                },
            )
            assert movement.status_code == 200, movement.text
            movement_id = str(movement.json()["movement"]["id"])
            posted = client.post(
                f"/api/v1/inventory/movements/{movement_id}/post",
                headers=checker_headers,
                json={"reason": "Independent HTTP review"},
            )
            on_hand = client.get(
                "/api/v1/inventory/on-hand",
                headers={**checker_headers, "X-ReconForge-Workspace": workspace_id},
                params={"organization": "ORG", "entity": "ENTITY", "workspace": "spoofed-workspace"},
            )
            snapshot = client.get(
                "/api/v1/inventory/snapshot",
                headers=checker_headers,
                params={"workspace": "spoofed-workspace"},
            )
            denied_workspace = client.get(
                "/api/v1/inventory/summary",
                headers={**checker_headers, "X-ReconForge-Workspace": "workspace-not-granted"},
            )

            assert all(response.status_code == 200 for response in (unit, item, warehouse, location, movement, posted)), [
                response.text for response in (unit, item, warehouse, location, movement, posted)
            ]
            assert on_hand.status_code == 200, on_hand.text
            assert on_hand.json()["source"]["kind"] == "postgresql-inventory-ledger"
            assert on_hand.json()["balances"][0]["quantity"] == "2.500"
            assert snapshot.status_code == 200, snapshot.text
            assert snapshot.json()["source"]["kind"] == "postgresql-inventory-core"
            assert snapshot.json()["summary"]["posted_movements"] == 1
            assert denied_workspace.status_code == 403
            assert denied_workspace.json()["error"]["code"] == "workspace_scope_denied"
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant_id,))
        except psycopg.Error:
            # Domain audit events are append-only; the disposable database is
            # removed by the live test runner after this contract completes.
            pass
        finally:
            admin.close()
