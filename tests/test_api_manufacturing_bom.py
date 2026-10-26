import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.manufacturing_bom import (
    BOMRegistrationPayload,
    ComponentLinePayload,
    ExplosionRequest,
    NettingRequest,
)
from reconforge.domain.manufacturing_bom_explosion import (
    BillOfMaterials,
    BOMComponentLine,
)
from reconforge.infrastructure.sqlite_manufacturing_bom import (
    SqliteManufacturingBOMRepository,
)


def test_bom_payload_schema_strictness() -> None:
    valid_component = {
        "line_number": 1,
        "component_item_id": "RAW-01",
        "component_name": "Steel Bolt",
        "component_type": "raw_material",
        "quantity_per_parent": 4,
        "scrap_factor_bps": 500,
        "substitute_item_id": None,
        "substitute_ratio_bps": 10000,
    }
    comp = ComponentLinePayload.model_validate(valid_component)
    assert comp.component_item_id == "RAW-01"
    assert comp.quantity_per_parent == 4

    valid_bom = {
        "bom_id": "BOM-100",
        "item_id": "ASSEMBLY-100",
        "revision": "A.1",
        "status": "approved",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "base_quantity": 1,
        "components": [valid_component],
    }
    bom_obj = BOMRegistrationPayload.model_validate(valid_bom)
    assert bom_obj.bom_id == "BOM-100"

    # Reject invalid date formats or negative quantities
    with pytest.raises(ValidationError):
        BOMRegistrationPayload.model_validate({**valid_bom, "effective_from": "01/01/2026"})

    with pytest.raises(ValidationError):
        BOMRegistrationPayload.model_validate({**valid_bom, "base_quantity": 0})


def test_explosion_request_schema_strictness() -> None:
    req = ExplosionRequest.model_validate({
        "item_id": "FG-01",
        "required_quantity": 10,
        "as_of_date": "2026-06-01",
    })
    assert req.item_id == "FG-01"
    assert req.required_quantity == 10

    with pytest.raises(ValidationError):
        ExplosionRequest.model_validate({
            "item_id": "FG-01",
            "required_quantity": -5,
            "as_of_date": "2026-06-01",
        })


def test_netting_request_schema_strictness() -> None:
    req = NettingRequest.model_validate({
        "item_id": "FG-01",
        "required_quantity": 10,
        "as_of_date": "2026-06-01",
        "inventory_on_hand": {"RAW-01": 5},
    })
    assert req.inventory_on_hand["RAW-01"] == 5


def test_sqlite_manufacturing_bom_lifecycle_and_explosion() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SqliteManufacturingBOMRepository(conn)

    # Subassembly
    sub = BillOfMaterials(
        bom_id="BOM-SUB-1",
        item_id="SUB-1",
        revision="REV-A",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(1, "RAW-01", "Component A", "raw_material", 2),
            BOMComponentLine(2, "RAW-02", "Component B", "raw_material", 5),
        ),
    )
    repo.save_bom(sub)

    # Finished Good
    fg = BillOfMaterials(
        bom_id="BOM-FG-1",
        item_id="FG-1",
        revision="REV-A",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(1, "SUB-1", "Subassembly", "subassembly", 3),
            BOMComponentLine(2, "RAW-03", "Fastener", "raw_material", 10, scrap_factor_bps=1000),  # 10% scrap
        ),
    )
    repo.save_bom(fg)

    # Retrieve and verify persistence
    retrieved_fg = repo.get_bom("FG-1")
    assert retrieved_fg is not None
    assert retrieved_fg.bom_id == "BOM-FG-1"
    assert len(retrieved_fg.components) == 2

    # Build engine and explode 10 units of FG-1
    engine = repo.build_engine()
    exploded = engine.explode("FG-1", 10, "2026-06-01")
    assert len(exploded) == 4

    # Depth 1: SUB-1 (30), RAW-03 (100 + 10 scrap = 110)
    sub_req = next(r for r in exploded if r.item_id == "SUB-1")
    assert sub_req.total_required_quantity == 30

    raw3_req = next(r for r in exploded if r.item_id == "RAW-03")
    assert raw3_req.total_required_quantity == 110

    # Depth 2: RAW-01 (30 * 2 = 60), RAW-02 (30 * 5 = 150)
    raw1_req = next(r for r in exploded if r.item_id == "RAW-01")
    assert raw1_req.total_required_quantity == 60

    # Test MRP netting
    inventory = {"RAW-01": 20, "RAW-02": 100, "RAW-03": 50, "SUB-1": 10}
    scheduled = {"RAW-01": 10, "RAW-02": 0, "RAW-03": 0, "SUB-1": 0}
    lot_rules = {"RAW-01": (50, 25)}  # min lot 50, multiple 25

    net_reqs = engine.calculate_net_requirements(exploded, inventory, scheduled, lot_rules)

    # RAW-01: Gross 60, Available 20+10=30 -> Net Shortage 30. Lot size min 50 -> Planned 50!
    n1 = next(n for n in net_reqs if n.item_id == "RAW-01")
    assert n1.gross_required == 60
    assert n1.net_shortage == 30
    assert n1.planned_order_quantity == 50


def test_bom_uom_scaling_and_eco_fields() -> None:
    comp = BOMComponentLine(
        line_number=1,
        component_item_id="RAW-RESIN",
        component_name="Polymer Resin",
        component_type="raw_material",
        quantity_per_parent=5,
        scrap_factor_bps=0,
        uom_id="KG",
        uom_conversion_factor_bps=20000,  # 2.0x factor
        eco_number="ECO-2026-99",
        change_reason="Switch to metric container",
    )
    assert comp.uom_id == "KG"
    assert comp.uom_conversion_factor_bps == 20000
    assert comp.eco_number == "ECO-2026-99"

    bom = BillOfMaterials(
        bom_id="BOM-CASE-01",
        item_id="FG-CASE",
        revision="REV-C",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(comp,),
        eco_number="ECO-2026-99",
        change_reason="Metric conversion",
    )
    from reconforge.domain.manufacturing_bom_explosion import BOMExplosionEngine

    engine = BOMExplosionEngine([bom])
    exploded = engine.explode("FG-CASE", 10, "2026-05-01")
    assert len(exploded) == 1
    # 5 * 10 = 50 base * (20000 / 10000) = 100 total required!
    assert exploded[0].total_required_quantity == 100


def test_postgres_bom_repository_scoping_and_rls() -> None:
    from unittest.mock import MagicMock

    from reconforge.infrastructure.postgres_manufacturing_bom import PostgresManufacturingBOMRepository

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_cursor.fetchone.return_value = ("tenant_bom_test", "org-a", "ws-a", "entity-a", "entity-a")
    def scoped_cursor(query: str, params: object = None) -> MagicMock:
        cursor = MagicMock()
        if "current_setting('app.tenant_id'" in query:
            cursor.fetchone.return_value = ("tenant_bom_test", "org-a", "ws-a", "entity-a", "entity-a")
        elif "domain_audit_ledger_state" in query:
            cursor.fetchone.return_value = {"last_sequence":0,"last_event_hash":"0"*64}
        return cursor
    mock_conn.execute.side_effect = scoped_cursor
    mock_conn.transaction.return_value.__enter__ = MagicMock(return_value=None)
    mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

    repo = PostgresManufacturingBOMRepository(mock_conn, "tenant_bom_test")
    assert repo.tenant_id == "tenant_bom_test"

    repo._scope()
    # Joining an active repository must preserve all five authenticated GUCs.
    assert "current_setting('app.tenant_id'" in mock_conn.execute.call_args_list[0].args[0]
    assert not any("set_config(" in call.args[0] for call in mock_conn.execute.call_args_list)


    # Test save_bom SQL contains eco_number and change_reason
    comp = BOMComponentLine(
        line_number=1,
        component_item_id="RAW-01",
        component_name="Component 1",
        component_type="raw_material",
        quantity_per_parent=1,
        eco_number="ECO-555",
        change_reason="Material change",
    )
    bom = BillOfMaterials(
        bom_id="BOM-PG-01",
        item_id="ITEM-PG-01",
        revision="REV-1",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(comp,),
        eco_number="ECO-555",
        change_reason="BOM ECO update",
    )
    repo.save_bom(workspace_id="ws_test", bom=bom, created_by="tester")
    assert mock_conn.execute.call_count >= 3


def test_manufacturing_bom_api_routes_and_server_mode_fail_closed(tmp_path: object) -> None:
    from pathlib import Path
    from typing import Any, cast

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from reconforge.api.errors import APIError, api_error_handler
    from reconforge.api.routes.manufacturing_bom import (
        require_bom_manage,
        require_bom_read,
        router,
    )
    from reconforge.auth.models import LocalUser

    db_path = str(Path(str(tmp_path)) / "bom_api_test.db")
    app = FastAPI()
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.include_router(router, prefix="/api/v1")
    app.state.db_path = db_path
    app.state.server_mode = False

    user = LocalUser(id="usr_eng", username="eng_user", display_name="Engineer")
    app.dependency_overrides[require_bom_read] = lambda: user
    app.dependency_overrides[require_bom_manage] = lambda: user

    client = TestClient(app)

    # 1. Register BOM with UOM scaling and ECO
    payload = {
        "bom_id": "BOM-API-01",
        "item_id": "ITEM-GEAR",
        "revision": "REV-A",
        "status": "approved",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "base_quantity": 1,
        "eco_number": "ECO-100",
        "change_reason": "Initial release",
        "components": [
            {
                "line_number": 1,
                "component_item_id": "STEEL-BAR",
                "component_name": "Alloy Steel Bar",
                "component_type": "raw_material",
                "quantity_per_parent": 2,
                "scrap_factor_bps": 500,
                "substitute_item_id": None,
                "substitute_ratio_bps": 10000,
                "uom_id": "M",
                "uom_conversion_factor_bps": 15000,  # 1.5x
                "eco_number": "ECO-100",
                "change_reason": "Design spec",
            }
        ],
    }
    resp = client.post("/api/v1/manufacturing/bom", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "success"

    # 2. Get BOM
    resp_get = client.get("/api/v1/manufacturing/bom/ITEM-GEAR")
    assert resp_get.status_code == 200
    assert resp_get.json()["bom_id"] == "BOM-API-01"
    assert resp_get.json()["item_id"] == "ITEM-GEAR"
    assert len(resp_get.json()["components"]) == 1

    # 3. Explode BOM via API
    resp_exp = client.post(
        "/api/v1/manufacturing/bom/explode",
        json={"item_id": "ITEM-GEAR", "required_quantity": 10, "as_of_date": "2026-06-01"},
    )
    assert resp_exp.status_code == 200
    lines = resp_exp.json()["exploded_lines"]
    assert len(lines) == 1
    assert lines[0]["gross_quantity"] == 20
    assert lines[0]["total_required_quantity"] == 21

    # 4. Fail-closed test in enterprise mode
    app_ent = FastAPI()
    app_ent.add_exception_handler(APIError, cast(Any, api_error_handler))
    app_ent.include_router(router, prefix="/api/v1")
    app_ent.state.server_mode = True
    app_ent.dependency_overrides[require_bom_read] = lambda: user

    client_ent = TestClient(app_ent)
    resp_fail = client_ent.get("/api/v1/manufacturing/bom/ITEM-GEAR")
    assert resp_fail.status_code == 503
    assert resp_fail.json()["error"]["code"] == "server_postgres_unavailable"
