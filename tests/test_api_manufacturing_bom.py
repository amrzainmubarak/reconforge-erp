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
