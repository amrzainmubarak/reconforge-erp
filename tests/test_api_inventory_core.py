from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.dependencies import get_db, get_local_db
from reconforge.api.routes.inventory_core import router
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.application.inventory_core import InventoryCoreSummary
from reconforge.auth.models import LocalUser


def _request(app: object) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/inventory/summary",
            "headers": [],
            "app": app,
        }
    )


def test_inventory_router_uses_the_explicit_local_database_boundary() -> None:
    route_dependencies: list[object] = []
    pending = [dependency for route in router.routes for dependency in route.dependant.dependencies]
    while pending:
        dependency = pending.pop()
        route_dependencies.append(dependency.call)
        pending.extend(dependency.dependencies)

    assert route_dependencies.count(get_local_db) == len(router.routes)
    assert get_db not in route_dependencies


def test_server_inventory_routes_bind_scope_and_use_postgres_adapter(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.inventory_core as inventory_routes
    from reconforge.api.server_inventory_core import InventoryExecutionScope

    user = LocalUser(id="inventory-user", username="inventory-user", display_name="Inventory User")
    permissions = frozenset({"inventory.read", "inventory.manage", "inventory.post"})
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeRepository:
        def upsert_uom(self, **values: object) -> dict[str, object]:
            calls.append(("upsert_uom", values))
            return {
                "uom_code": values["uom_code"],
                "workspace_id": values["workspace"],
                "unknown_future_column": "must-not-escape",
            }

        def list_uoms(self, **values: object) -> list[dict[str, object]]:
            calls.append(("list_uoms", values))
            return [{"uom_code": "EA", "unknown_future_column": "must-not-escape"}]

        def summary(self, **values: object) -> InventoryCoreSummary:
            calls.append(("summary", values))
            return InventoryCoreSummary(str(values["workspace"]), 1, 0, 0, 0, 0, 0, 0, 0)

        def snapshot(self, **values: object) -> dict[str, object]:
            calls.append(("snapshot", values))
            return {
                "schema_version": 1,
                "source": {"kind": "postgresql-inventory-core", "unknown_source_field": "must-not-escape"},
                "workspace": str(values["workspace"]),
                "summary": {"workspace": str(values["workspace"]), "unknown_summary_field": "must-not-escape"},
                "units_of_measure": [{"id": "uom-1", "unknown_uom_field": "must-not-escape"}],
                "items": [],
                "warehouses": [],
                "locations": [],
                "lots_and_serials": [],
                "movements": [{"id": "movement-1", "unknown_movement_field": "must-not-escape"}],
                "unknown_snapshot_field": "must-not-escape",
            }

        def list_movements(self, **values: object) -> list[dict[str, object]]:
            calls.append(("list_movements", values))
            return [{"id": "movement-1", "unknown_movement_field": "must-not-escape"}]

        def create_movement(self, **values: object) -> dict[str, object]:
            calls.append(("create_movement", values))
            return {"id": "movement-1", "unknown_movement_field": "must-not-escape"}

        def get_movement(self, movement_id: str, **values: object) -> dict[str, object]:
            calls.append(("get_movement", {"movement_id": movement_id, **values}))
            return {"id": movement_id, "unknown_movement_field": "must-not-escape"}

        def post_movement(self, movement_id: str, **values: object) -> dict[str, object]:
            calls.append(("post_movement", {"movement_id": movement_id, **values}))
            return {"id": movement_id, "unknown_movement_field": "must-not-escape"}

        def void_movement(self, movement_id: str, **values: object) -> dict[str, object]:
            calls.append(("void_movement", {"movement_id": movement_id, **values}))
            return {"id": movement_id, "unknown_movement_field": "must-not-escape"}

        def on_hand(self, **values: object) -> dict[str, object]:
            calls.append(("on_hand", values))
            return {
                "schema_version": 1,
                "source": {"kind": "postgresql-inventory-ledger", "unknown_source_field": "must-not-escape"},
                "workspace": str(values["workspace"]),
                "organization_code": "ORG",
                "entity_code": "ENTITY",
                "summary": {"rows": 1, "negative_rows": 0, "unknown_summary_field": "must-not-escape"},
                "balances": [{"item_code": "ITEM", "unknown_balance_field": "must-not-escape"}],
                "unknown_on_hand_field": "must-not-escape",
            }

        def control_exceptions(self, **values: object) -> dict[str, object]:
            calls.append(("control_exceptions", values))
            return {
                "schema_version": 1,
                "generated_at": "2026-08-26T00:00:00Z",
                "as_of": "2026-08-26",
                "source": {"kind": "postgresql-inventory-controls", "unknown_source_field": "must-not-escape"},
                "workspace": str(values["workspace"]),
                "organization_code": "ORG",
                "entity_code": "ENTITY",
                "summary": {"total": 1, "high": 1, "medium": 0, "unknown_summary_field": "must-not-escape"},
                "exceptions": [{"exception_id": "INVEX-1", "unknown_exception_field": "must-not-escape"}],
                "unknown_controls_field": "must-not-escape",
            }

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "inventory-token" else None

    def execute(request: Any, operation: Any, **kwargs: object) -> Any:
        assert request_tenant_id(request) == "tenant-a"
        return operation(
            FakeRepository(),
            InventoryExecutionScope(
                RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
                organization_code="ORG",
                entity_code="ENTITY",
            ),
        )

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)
    monkeypatch.setattr(
        inventory_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
    )
    monkeypatch.setattr(inventory_routes, "enforce_server_scoped_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inventory_routes, "enforce_server_scoped_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inventory_routes, "execute_postgres_inventory", execute)

    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tmp_path / "tenants",
            postgres_dsn="postgresql://inventory.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {
        "X-ReconForge-Tenant": "tenant-a",
        "X-ReconForge-Workspace": "workspace-a",
        "Authorization": "Bearer inventory-token",
    }
    saved = client.post(
        "/api/v1/inventory/units",
        headers=headers,
        json={"uom_code": "EA", "name": "Each", "workspace": "spoofed-workspace"},
    )
    summarized = client.get("/api/v1/inventory/summary", headers=headers)
    listed = client.get("/api/v1/inventory/units", headers=headers)
    snapshotted = client.get("/api/v1/inventory/snapshot", headers=headers)
    movements = client.get("/api/v1/inventory/movements", headers=headers)
    created_movement = client.post(
        "/api/v1/inventory/movements",
        headers=headers,
        json={
            "movement_number": "MOV-001",
            "movement_type": "Receipt",
            "organization_code": "ORG",
            "entity_code": "ENTITY",
            "period_id": "period-a",
            "movement_date": "2026-08-26",
            "description": "Test movement",
            "lines": [{"item_code": "ITEM", "quantity": "1"}],
        },
    )
    movement_detail = client.get("/api/v1/inventory/movements/movement-1", headers=headers)
    on_hand = client.get("/api/v1/inventory/on-hand?organization=ORG&entity=ENTITY", headers=headers)
    controls = client.get(
        "/api/v1/inventory/control-exceptions?organization=ORG&entity=ENTITY",
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    assert summarized.status_code == 200, summarized.text
    assert listed.status_code == 200, listed.text
    assert snapshotted.status_code == 200, snapshotted.text
    assert movements.status_code == 200, movements.text
    assert created_movement.status_code == 200, created_movement.text
    assert movement_detail.status_code == 200, movement_detail.text
    assert on_hand.status_code == 200, on_hand.text
    assert controls.status_code == 200, controls.text
    assert "unknown_future_column" not in saved.text
    assert "unknown_future_column" not in listed.text
    assert all(
        "must-not-escape" not in response.text
        for response in (
            snapshotted,
            movements,
            created_movement,
            movement_detail,
            on_hand,
            controls,
        )
    )
    assert next(values for name, values in calls if name == "upsert_uom")["workspace"] == "workspace-a"
    assert next(values for name, values in calls if name == "summary")["workspace"] == "workspace-a"
