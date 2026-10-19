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


def test_date_effective_multi_revision_selection() -> None:
    # Item FG-REV with REV-1 (H1 2026) and REV-2 (H2 2026)
    bom_rev1 = BillOfMaterials(
        bom_id="BOM-REV-1",
        item_id="FG-REV",
        revision="REV-1",
        status="approved",
        effective_from="2026-01-01",
        effective_to="2026-06-30",
        base_quantity=1,
        components=(BOMComponentLine(1, "RAW-OLD", "Old Part", "raw_material", 2),),
    )
    bom_rev2 = BillOfMaterials(
        bom_id="BOM-REV-2",
        item_id="FG-REV",
        revision="REV-2",
        status="approved",
        effective_from="2026-07-01",
        effective_to="2026-12-31",
        base_quantity=1,
        components=(BOMComponentLine(1, "RAW-NEW", "New Part", "raw_material", 3),),
    )

    engine = BOMExplosionEngine([bom_rev1, bom_rev2])

    # Explode on 2026-03-15 -> should pick REV-1
    exp_h1 = engine.explode("FG-REV", 5, "2026-03-15")
    assert len(exp_h1) == 1
    assert exp_h1[0].item_id == "RAW-OLD"
    assert exp_h1[0].total_required_quantity == 10

    # Explode on 2026-09-01 -> should pick REV-2
    exp_h2 = engine.explode("FG-REV", 5, "2026-09-01")
    assert len(exp_h2) == 1
    assert exp_h2[0].item_id == "RAW-NEW"
    assert exp_h2[0].total_required_quantity == 15

    # Explode on 2027-01-15 (after REV-2 expired) -> should fail
    with pytest.raises(Exception, match="No approved BOM for FG-REV effective on 2027-01-15"):
        engine.explode("FG-REV", 5, "2027-01-15")

    # Explode with specific revision REV-1 on 2026-09-01 (when REV-1 is expired) -> should fail
    with pytest.raises(Exception, match="expired on 2026-06-30"):
        engine.explode("FG-REV", 5, "2026-09-01", specific_revision="REV-1")


def test_component_substitution_at_explosion_time() -> None:
    # BOM has primary component RAW-A with substitute RAW-A-SUB (ratio 1.5:1 = 15,000 bps)
    bom = BillOfMaterials(
        bom_id="BOM-SUBST",
        item_id="FG-SUBST",
        revision="REV-A",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(
                1,
                "RAW-A",
                "Primary Part A",
                "raw_material",
                10,
                substitute_item_id="RAW-A-SUB",
                substitute_ratio_bps=15_000,  # 1.5 ratio
            ),
            BOMComponentLine(2, "RAW-B", "Standard Part B", "raw_material", 5),
        ),
    )

    engine = BOMExplosionEngine([bom])

    # Explode without substitution -> RAW-A is used
    exp_standard = engine.explode("FG-SUBST", 2, "2026-05-01")
    req_a = next(r for r in exp_standard if r.item_id == "RAW-A")
    assert not req_a.is_substituted
    assert req_a.original_item_id is None
    assert req_a.total_required_quantity == 20

    # Explode with preferred_substitutions={"RAW-A"} -> RAW-A-SUB is used with 1.5x quantity
    # Base qty = 20 * 15,000 / 10,000 = 30 units
    exp_sub = engine.explode("FG-SUBST", 2, "2026-05-01", preferred_substitutions=frozenset({"RAW-A"}))
    req_sub = next(r for r in exp_sub if r.item_id == "RAW-A-SUB")
    assert req_sub.is_substituted
    assert req_sub.original_item_id == "RAW-A"
    assert req_sub.total_required_quantity == 30

    # Part B remains untouched
    req_b = next(r for r in exp_sub if r.item_id == "RAW-B")
    assert not req_b.is_substituted
    assert req_b.total_required_quantity == 10


def test_substitute_inventory_netting() -> None:
    bom = BillOfMaterials(
        bom_id="BOM-NET-SUB",
        item_id="FG-NET",
        revision="REV-1",
        status="approved",
        effective_from="2026-01-01",
        effective_to=None,
        base_quantity=1,
        components=(
            BOMComponentLine(
                1,
                "RAW-COPPER",
                "Copper Rod",
                "raw_material",
                100,
                substitute_item_id="RAW-BRASS",
                substitute_ratio_bps=10_000,  # 1:1 substitute
            ),
        ),
    )
    engine = BOMExplosionEngine([bom])
    exploded = engine.explode("FG-NET", 1, "2026-05-01")  # Demand: 100 Copper

    # Inventory:
    # RAW-COPPER: On hand = 40, On order = 0 -> Initial shortage = 60.
    # RAW-BRASS (substitute): On hand = 50.
    # Netting should consume 50 units of Brass to cover 50 units of Copper shortage!
    # Remaining shortage of Copper = 60 - 50 = 10 units!
    inventory = {"RAW-COPPER": 40, "RAW-BRASS": 50}
    scheduled = {"RAW-COPPER": 0, "RAW-BRASS": 0}

    net_reqs = engine.calculate_net_requirements(exploded, inventory, scheduled)

    copper = next(n for n in net_reqs if n.item_id == "RAW-COPPER")
    assert copper.gross_required == 100
    assert copper.net_shortage == 10
    assert copper.planned_order_quantity == 10


def test_mrp_shortage_requisition_generation_and_deduplication() -> None:
    from reconforge.domain.manufacturing_supply_plan import (
        MRPShortageRequisition,
        generate_mrp_shortage_requisitions,
    )

    requirements = [
        {"item_id": "RAW-STEEL", "shortage_quantity_scaled": 1000, "planned_order_quantity_scaled": 1000},
        {"item_id": "RAW-PLASTIC", "shortage_quantity_scaled": 500, "planned_order_quantity_scaled": 500},
        {"item_id": "RAW-BOLTS", "shortage_quantity_scaled": 0, "planned_order_quantity_scaled": 0},  # No shortage
    ]

    # Initial run: no existing procurement claims
    reqs = generate_mrp_shortage_requisitions(
        plan_id="PLAN-2026-001",
        requirements=requirements,
        required_date="2026-07-01",
        unit_prices_minor={"RAW-STEEL": 250, "RAW-PLASTIC": 120},
    )

    assert len(reqs) == 2
    steel_req = next(r for r in reqs if r.item_id == "RAW-STEEL")
    assert isinstance(steel_req, MRPShortageRequisition)
    assert steel_req.shortage_quantity_scaled == 1000
    assert steel_req.planned_order_quantity_scaled == 1000
    assert steel_req.unit_price_minor == 250

    # Re-running with same inputs produces identical deterministic idempotency keys
    reqs_repeat = generate_mrp_shortage_requisitions(
        plan_id="PLAN-2026-001",
        requirements=requirements,
        required_date="2026-07-01",
        unit_prices_minor={"RAW-STEEL": 250, "RAW-PLASTIC": 120},
    )
    assert reqs[0].idempotency_key == reqs_repeat[0].idempotency_key
    assert reqs[0].requisition_id == reqs_repeat[0].requisition_id

    # Second run with existing active claims covering RAW-STEEL completely and RAW-PLASTIC partially
    claims = {
        "RAW-STEEL": [1000],  # 1000 claimed -> 0 headroom remaining
        "RAW-PLASTIC": [300],  # 300 claimed -> 200 headroom remaining
    }
    reqs_second_run = generate_mrp_shortage_requisitions(
        plan_id="PLAN-2026-001",
        requirements=requirements,
        existing_claims=claims,
        required_date="2026-07-01",
    )

    # RAW-STEEL is suppressed (zero headroom, preventing duplicate supply!)
    # RAW-PLASTIC generates a requisition for remaining headroom (200)
    assert len(reqs_second_run) == 1
    assert reqs_second_run[0].item_id == "RAW-PLASTIC"
    assert reqs_second_run[0].shortage_quantity_scaled == 200
    assert reqs_second_run[0].planned_order_quantity_scaled == 200
