"""Tests for multi-level BOM explosion, cycle detection, scrap, and net requirements."""

import pytest

from reconforge.domain.manufacturing_bom_explosion import (
    BillOfMaterials,
    BOMComponentLine,
    BOMExplosionEngine,
)


def test_bom_multi_level_explosion() -> None:
    # Finished Good: FG-001 composed of:
    # - 2 x SUB-01 (Subassembly)
    # - 4 x RAW-01 (Raw Material, with 500 bps = 5% scrap)
    #
    # Subassembly: SUB-01 composed of:
    # - 3 x RAW-02 (Raw Material)
    # - 1 x RAW-03 (Raw Material)

    bom_sub = BillOfMaterials(
        bom_id="BOM-SUB-01",
        item_id="SUB-01",
        revision="REV-A",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(1, "RAW-02", "Resistor", "raw_material", 3),
            BOMComponentLine(2, "RAW-03", "Capacitor", "raw_material", 1),
        ),
    )

    bom_fg = BillOfMaterials(
        bom_id="BOM-FG-001",
        item_id="FG-001",
        revision="REV-01",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(1, "SUB-01", "Circuit Board", "subassembly", 2),
            BOMComponentLine(2, "RAW-01", "Aluminium Casing", "raw_material", 4, scrap_factor_bps=500),  # 5% scrap
        ),
    )

    engine = BOMExplosionEngine([bom_fg, bom_sub])

    # Explode 10 units of FG-001
    exploded = engine.explode("FG-001", 10, "2026-06-01")

    # Expected requirements:
    # Depth 1:
    # - SUB-01: 10 * 2 = 20 units
    # - RAW-01: 10 * 4 = 40 base + (40 * 500 + 5000)//10000 = 40 + 2 = 42 units (with scrap)
    # Depth 2 (from 20 units of SUB-01):
    # - RAW-02: 20 * 3 = 60 units
    # - RAW-03: 20 * 1 = 20 units

    assert len(exploded) == 4

    sub_req = next(r for r in exploded if r.item_id == "SUB-01")
    assert sub_req.depth == 1
    assert sub_req.total_required_quantity == 20

    raw1_req = next(r for r in exploded if r.item_id == "RAW-01")
    assert raw1_req.depth == 1
    assert raw1_req.gross_quantity == 40
    assert raw1_req.scrap_quantity == 2
    assert raw1_req.total_required_quantity == 42

    raw2_req = next(r for r in exploded if r.item_id == "RAW-02")
    assert raw2_req.depth == 2
    assert raw2_req.total_required_quantity == 60

    raw3_req = next(r for r in exploded if r.item_id == "RAW-03")
    assert raw3_req.depth == 2
    assert raw3_req.total_required_quantity == 20


def test_bom_cycle_detection() -> None:
    # Circular: A requires B, and B requires A!
    bom_a = BillOfMaterials(
        bom_id="BOM-A",
        item_id="ITEM-A",
        revision="R1",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(BOMComponentLine(1, "ITEM-B", "Item B", "subassembly", 1),),
    )
    bom_b = BillOfMaterials(
        bom_id="BOM-B",
        item_id="ITEM-B",
        revision="R1",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(BOMComponentLine(1, "ITEM-A", "Item A", "subassembly", 1),),
    )

    engine = BOMExplosionEngine([bom_a, bom_b])

    with pytest.raises(Exception, match="Circular dependency"):
        engine.explode("ITEM-A", 1, "2026-06-01")


def test_mrp_netting_with_lot_sizing() -> None:
    bom = BillOfMaterials(
        bom_id="BOM-P1",
        item_id="P1",
        revision="R1",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(1, "RAW-STEEL", "Steel Sheet", "raw_material", 50),
            BOMComponentLine(2, "RAW-BOLT", "Hex Bolt", "raw_material", 100),
        ),
    )

    engine = BOMExplosionEngine([bom])
    exploded = engine.explode("P1", 2, "2026-06-01")  # Demand: 100 Steel, 200 Bolts

    # Inventory:
    # RAW-STEEL: On hand = 40, On order = 20 -> Total available = 60. Net shortage = 100 - 60 = 40.
    # Lot sizing for Steel: min_lot = 50, lot_multiple = 25 -> 40 becomes min_lot 50!
    #
    # RAW-BOLT: On hand = 250, On order = 0 -> Total available = 250. Shortage = 0.
    inventory = {"RAW-STEEL": 40, "RAW-BOLT": 250}
    scheduled = {"RAW-STEEL": 20, "RAW-BOLT": 0}
    lot_rules = {"RAW-STEEL": (50, 25), "RAW-BOLT": (100, 50)}

    net_reqs = engine.calculate_net_requirements(exploded, inventory, scheduled, lot_rules)

    steel = next(n for n in net_reqs if n.item_id == "RAW-STEEL")
    assert steel.gross_required == 100
    assert steel.net_shortage == 40
    assert steel.planned_order_quantity == 50  # Rounded up to min lot!

    bolt = next(n for n in net_reqs if n.item_id == "RAW-BOLT")
    assert bolt.gross_required == 200
    assert bolt.net_shortage == 0
    assert bolt.planned_order_quantity == 0
