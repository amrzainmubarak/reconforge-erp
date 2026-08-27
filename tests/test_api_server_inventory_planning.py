"""Live PostgreSQL HTTP contract for Inventory Planning."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from reconforge.api import create_api_app
from reconforge.api.routes import inventory_planning as routes
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
from reconforge.infrastructure.postgres_inventory_planning import POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_master_data_application import install_postgres_master_data_application_schema


def test_inventory_planning_routes_drop_future_adapter_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    session = {
        "id": "count-1",
        "status": "Counting",
        "lines": [{"id": "line-1", "item_code": "ITEM-1", "expected_quantity": "2.500", "unknown": "must-not-escape"}],
        "summary": {"lines": 1, "counted_lines": 0, "variance_lines": 0, "unknown": "must-not-escape"},
        "unknown_session_field": "must-not-escape",
    }
    rule = {
        "id": "rule-1",
        "item_code": "ITEM-1",
        "minimum_quantity": "3.000",
        "target_quantity": "5.000",
        "unknown_rule_field": "must-not-escape",
    }
    signals = {
        "schema_version": 1,
        "source": {"kind": "local-inventory-reorder-controls", "unknown": "must-not-escape"},
        "summary": {"total": 1, "high": 0, "medium": 1, "unknown": "must-not-escape"},
        "pagination": {"limit": 100, "offset": 0, "returned": 1, "unknown": "must-not-escape"},
        "signals": [{"signal_id": "signal-1", "rule_id": "rule-1", "risk_rating": "medium", "unknown": "must-not-escape"}],
        "unknown_signals_field": "must-not-escape",
    }
    snapshot = {
        "schema_version": 1,
        "source": {"kind": "local-inventory-planning", "unknown": "must-not-escape"},
        "workspace": "default",
        "summary": {"workspace": "default", "sessions": 1, "unknown": "must-not-escape"},
        "count_sessions": [session],
        "reorder_rules": [rule],
        "unknown_snapshot_field": "must-not-escape",
    }
    responses: list[Any] = [session, [session], session, snapshot, rule, [rule], signals]

    monkeypatch.setattr(routes, "server_inventory_planning_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_server_call", lambda *_args, **_kwargs: responses.pop(0))

    created = routes.create_count_session(
        request,
        routes.CountSessionRequest(
            count_number="COUNT-1",
            organization_code="ORG",
            entity_code="ENTITY",
            period_id="PERIOD",
            warehouse_code="MAIN",
            location_code="STOCK",
            count_date="2026-07-28",
        ),
        user,
        None,
    )
    listed = routes.list_count_sessions(request, user, None, workspace="default", limit=10, offset=0)
    fetched = routes.get_count_session("count-1", request, user, None)
    planned = routes.snapshot(request, user, None, workspace="default")
    saved_rule = routes.upsert_reorder_rule(
        request,
        routes.ReorderRuleRequest(
            organization_code="ORG",
            entity_code="ENTITY",
            item_code="ITEM-1",
            warehouse_code="MAIN",
            location_code="STOCK",
            minimum_quantity="3.000",
            target_quantity="5.000",
        ),
        user,
        None,
    )
    rules = routes.list_reorder_rules(request, user, None, workspace="default", limit=10, offset=0)
    reorder = routes.reorder_signals("ORG", "ENTITY", request, user, None, workspace="default", limit=10, offset=0)

    def resource_id(response: dict[str, object], key: str, field: str = "id") -> str:
        value = response[key]
        if isinstance(value, dict):
            return str(value[field])
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return str(value[0][field])
        raise AssertionError(f"Unexpected response shape for {key}")

    assert resource_id(created, "count_session") == "count-1"
    assert resource_id(listed, "count_sessions") == "count-1"
    assert resource_id(fetched, "count_session") == "count-1"
    assert resource_id(planned, "count_sessions") == "count-1"
    assert resource_id(saved_rule, "reorder_rule") == "rule-1"
    assert resource_id(rules, "reorder_rules") == "rule-1"
    assert resource_id(reorder, "signals", "signal_id") == "signal-1"
    assert "must-not-escape" not in str([created, listed, fetched, planned, saved_rule, rules, reorder])


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_inventory_planning_http_lifecycle_is_scoped_exact_and_human_governed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_id = f"planning_http_{token}"
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
            admin.execute(POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL)
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
                "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,active) VALUES (%s,%s,'ORG','Organization','USD',TRUE)",
                (tenant_id, organization_id),
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
                "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number) VALUES (%s,%s,'2026-07','2026-07-01','2026-07-31',2026,7)",
                (tenant_id, period_id),
            )
            connection.execute(
                "INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES (%s,%s,%s)",
                (tenant_id, workspace_id, period_id),
            )
            inventory = PostgresInventoryCoreRepository(connection, tenant_id)
            inventory.upsert_uom(uom_code="KG", name="Kilogram", category="Weight", decimal_places=3, workspace=workspace_id)
            inventory.upsert_item(item_code="MATERIAL", name="Material", organization_code="ORG", uom_code="KG", workspace=workspace_id)
            inventory.upsert_warehouse(warehouse_code="MAIN", name="Main", organization_code="ORG", entity_code="ENTITY", workspace=workspace_id)
            inventory.upsert_location(warehouse_code="MAIN", location_code="STOCK", name="Stock", organization_code="ORG", workspace=workspace_id)
            movement = inventory.create_movement(
                movement_number="RCPT-PLANNING-HTTP",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=period_id,
                movement_date="2026-07-27",
                description="Synthetic planning receipt",
                lines=[{"item_code": "MATERIAL", "quantity": "2.500", "to_location": "MAIN/STOCK"}],
                workspace=workspace_id,
                actor_label="seed",
            )
            inventory.post_movement(str(movement["id"]), reason="Seed", actor_label="seed-checker")

        maker = LocalUser(id=f"maker-{token}", username=f"maker-{token}", display_name="Maker")
        checker = LocalUser(id=f"checker-{token}", username=f"checker-{token}", display_name="Checker")
        planner = LocalUser(id=f"planner-{token}", username=f"planner-{token}", display_name="Planner")
        scope = PrincipalScopeSnapshot(
            workspace_ids=frozenset({workspace_id}),
            organization_ids=frozenset({organization_id}),
            legal_entity_ids=frozenset({entity_id}),
        )

        def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
            if credential == "maker-token":
                return AuthenticatedServerRequest(user=maker, permissions=frozenset({"inventory.read", "inventory.count.manage"}), principal_type="user", scope_authority=scope)
            if credential == "checker-token":
                return AuthenticatedServerRequest(user=checker, permissions=frozenset({"inventory.read", "inventory.count.approve"}), principal_type="user", scope_authority=scope)
            if credential == "planner-token":
                return AuthenticatedServerRequest(user=planner, permissions=frozenset({"inventory.read", "inventory.reorder.manage"}), principal_type="user", scope_authority=scope)
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
            planner_headers = {**base, "Authorization": "Bearer planner-token"}
            created = client.post(
                "/api/v1/inventory-planning/counts",
                headers=maker_headers,
                json={
                    "count_number": "COUNT-HTTP-1",
                    "organization_code": "ORG",
                    "entity_code": "ENTITY",
                    "period_id": period_id,
                    "warehouse_code": "MAIN",
                    "location_code": "STOCK",
                    "count_date": "2026-07-28",
                    "workspace": "spoofed-workspace",
                },
            )
            assert created.status_code == 200, created.text
            session_id = str(created.json()["count_session"]["id"])
            started = client.post(f"/api/v1/inventory-planning/counts/{session_id}/start", headers=maker_headers)
            assert started.status_code == 200, started.text
            line_id = str(started.json()["count_session"]["lines"][0]["id"])
            assert started.json()["count_session"]["lines"][0]["expected_quantity"] == "2.500"
            counted = client.post(
                f"/api/v1/inventory-planning/counts/{session_id}/lines/{line_id}",
                headers=maker_headers,
                json={"counted_quantity": "2.000", "note": "Synthetic HTTP count"},
            )
            assert counted.status_code == 200, counted.text
            submitted = client.post(
                f"/api/v1/inventory-planning/counts/{session_id}/submit",
                headers=maker_headers,
                json={"reason": "Count complete"},
            )
            assert submitted.status_code == 200, submitted.text
            maker_approval = client.post(
                f"/api/v1/inventory-planning/counts/{session_id}/approve",
                headers=maker_headers,
                json={"reason": "Self approval"},
            )
            assert maker_approval.status_code == 403
            approved = client.post(
                f"/api/v1/inventory-planning/counts/{session_id}/approve",
                headers=checker_headers,
                json={"reason": "Independent approval"},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["count_session"]["status"] == "Approved"
            assert approved.json()["count_session"]["lines"][0]["variance_quantity"] == "-0.500"
            rule = client.post(
                "/api/v1/inventory-planning/reorder-rules",
                headers=planner_headers,
                json={
                    "organization_code": "ORG",
                    "entity_code": "ENTITY",
                    "item_code": "MATERIAL",
                    "warehouse_code": "MAIN",
                    "location_code": "STOCK",
                    "minimum_quantity": "3.000",
                    "target_quantity": "5.000",
                    "lead_time_days": 2,
                    "workspace": "spoofed-workspace",
                },
            )
            assert rule.status_code == 200, rule.text
            signals = client.get(
                "/api/v1/inventory-planning/reorder-signals",
                headers=planner_headers,
                params={"organization": "ORG", "entity": "ENTITY", "workspace": "spoofed-workspace"},
            )
            denied_workspace = client.get(
                "/api/v1/inventory-planning/summary",
                headers={**checker_headers, "X-ReconForge-Workspace": "workspace-not-granted"},
            )
            assert signals.status_code == 200, signals.text
            assert signals.json()["summary"]["total"] == 1
            assert signals.json()["signals"][0]["suggested_quantity"] == "2.500"
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
