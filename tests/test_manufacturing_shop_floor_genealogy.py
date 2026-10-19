"""Domain invariant and genealogy tests for Shop Floor Execution and Traceability."""

from __future__ import annotations

import pytest

from reconforge.domain.shop_floor_dispatch import (
    LotTraceabilityRecord,
    ShopFloorExecutionError,
    ShopFloorOperationStep,
    WorkOrderDispatch,
    traverse_genealogy,
    validate_step_progression,
)


def test_lot_traceability_record_validations():
    """Verify validation of identifiers, positive quantity, and scale factor."""
    lot = LotTraceabilityRecord(
        workspace_id="ws_main",
        lot_id="LOT-RM-001",
        item_id="STEEL-SHEET-01",
        batch_number="B-2026-X1",
        quantity_scaled=500_000,
        scale_factor=1000,
        status="active",
        notes="Heat treatment cert #9921",
    )
    assert lot.lot_id == "LOT-RM-001"
    assert lot.quantity_scaled == 500_000

    # Non-positive quantity rejected
    with pytest.raises(ShopFloorExecutionError, match="quantity must be positive"):
        LotTraceabilityRecord(
            workspace_id="ws_main",
            lot_id="LOT-RM-002",
            item_id="STEEL-SHEET-01",
            batch_number="B-2026-X2",
            quantity_scaled=0,
        )


def test_routing_step_progression_and_quantity_conservation():
    """Verify contiguous sequence progression and quantity conservation invariants."""
    step1 = ShopFloorOperationStep(
        step_id="STEP-01",
        work_order_id="WO-100",
        operation_sequence=1,
        work_center_id="WC-CUTTING",
        operator_id="OP-44",
        status="completed",
        actual_run_minutes=45,
        quantity_completed_scaled=10_000,
        quantity_scrapped_scaled=500,
    )
    step2 = ShopFloorOperationStep(
        step_id="STEP-02",
        work_order_id="WO-100",
        operation_sequence=2,
        work_center_id="WC-WELDING",
        operator_id="OP-88",
        status="in_progress",
        actual_run_minutes=30,
        quantity_completed_scaled=0,
        quantity_scrapped_scaled=0,
    )

    dispatch = WorkOrderDispatch(
        workspace_id="ws_main",
        dispatch_id="DISP-01",
        work_order_id="WO-100",
        item_id="CHASSIS-01",
        scheduled_quantity_scaled=12_000,
        dispatched_lot_id="LOT-CHASSIS-01",
        dispatched_at="2026-10-19T08:00:00Z",
        steps=(step1, step2),
    )

    # Valid step 1 execution
    validate_step_progression(dispatch, step1)

    # Incomplete prior step failure: if step 1 were pending, step 2 cannot complete
    pending_step1 = ShopFloorOperationStep(
        step_id="STEP-01",
        work_order_id="WO-100",
        operation_sequence=1,
        work_center_id="WC-CUTTING",
        operator_id="OP-44",
        status="pending",
        actual_run_minutes=0,
        quantity_completed_scaled=0,
        quantity_scrapped_scaled=0,
    )
    pending_dispatch = WorkOrderDispatch(
        workspace_id="ws_main",
        dispatch_id="DISP-02",
        work_order_id="WO-100",
        item_id="CHASSIS-01",
        scheduled_quantity_scaled=12_000,
        dispatched_lot_id="LOT-CHASSIS-02",
        dispatched_at="2026-10-19T08:00:00Z",
        steps=(pending_step1, step2),
    )
    with pytest.raises(ShopFloorExecutionError, match="prior sequence 1 has status 'pending'"):
        validate_step_progression(pending_dispatch, step2)

    # Exceeding scheduled quantity failure
    excessive_step = ShopFloorOperationStep(
        step_id="STEP-01",
        work_order_id="WO-100",
        operation_sequence=1,
        work_center_id="WC-CUTTING",
        operator_id="OP-44",
        status="completed",
        actual_run_minutes=60,
        quantity_completed_scaled=11_000,
        quantity_scrapped_scaled=2_000,  # 13,000 > scheduled 12,000!
    )
    with pytest.raises(ShopFloorExecutionError, match="exceeds scheduled dispatch quantity"):
        validate_step_progression(dispatch, excessive_step)


def test_genealogy_bidirectional_traversal_and_cycle_prevention():
    """Verify backward consumption tracing, forward recall tracing, and cycle detection."""
    # Graph:
    # RAW-1, RAW-2 -> SUBASSY-A
    # SUBASSY-A, RAW-3 -> FINISHED-X
    edges = [
        ("LOT-RAW-1", "LOT-SUBASSY-A", 100),
        ("LOT-RAW-2", "LOT-SUBASSY-A", 200),
        ("LOT-SUBASSY-A", "LOT-FINISHED-X", 50),
        ("LOT-RAW-3", "LOT-FINISHED-X", 75),
    ]
    item_map = {
        "LOT-RAW-1": "RAW-STEEL",
        "LOT-RAW-2": "RAW-PLASTIC",
        "LOT-RAW-3": "RAW-SCREWS",
        "LOT-SUBASSY-A": "SUB-MODULE-A",
        "LOT-FINISHED-X": "FG-MACHINE-X",
    }

    # Backward genealogy for FINISHED-X
    backward_tree = traverse_genealogy("LOT-FINISHED-X", edges, item_map, direction="backward")
    assert backward_tree.lot_id == "LOT-FINISHED-X"
    assert len(backward_tree.children) == 2
    child_lots = {c.lot_id for c in backward_tree.children}
    assert "LOT-SUBASSY-A" in child_lots
    assert "LOT-RAW-3" in child_lots

    subassy_node = next(c for c in backward_tree.children if c.lot_id == "LOT-SUBASSY-A")
    assert len(subassy_node.children) == 2
    sub_raw_lots = {c.lot_id for c in subassy_node.children}
    assert sub_raw_lots == {"LOT-RAW-1", "LOT-RAW-2"}

    # Forward genealogy (recall analysis): if LOT-RAW-1 is defective, where was it used?
    forward_tree = traverse_genealogy("LOT-RAW-1", edges, item_map, direction="forward")
    assert forward_tree.lot_id == "LOT-RAW-1"
    assert len(forward_tree.children) == 1
    assert forward_tree.children[0].lot_id == "LOT-SUBASSY-A"
    assert forward_tree.children[0].children[0].lot_id == "LOT-FINISHED-X"

    # Cycle detection
    cyclic_edges = [
        ("LOT-A", "LOT-B", 10),
        ("LOT-B", "LOT-C", 10),
        ("LOT-C", "LOT-A", 10),  # Cycle!
    ]
    with pytest.raises(ShopFloorExecutionError, match="cycle detected"):
        traverse_genealogy("LOT-A", cyclic_edges, {}, direction="forward")
