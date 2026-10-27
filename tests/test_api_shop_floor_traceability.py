"""Tests for Shop Floor Traceability API schemas and SQLite repository."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.shop_floor_traceability import (
    LotRegistrationRequest,
)
from reconforge.domain.shop_floor_dispatch import (
    LotTraceabilityRecord,
    ShopFloorOperationStep,
    WorkOrderDispatch,
    traverse_genealogy,
)
from reconforge.infrastructure.sqlite_shop_floor import SqliteShopFloorRepository


def test_shop_floor_pydantic_schemas():
    """Verify input validation rules and error rejection."""
    valid_lot = {
        "lot_id": "LOT-001",
        "item_id": "ITEM-100",
        "batch_number": "BATCH-2026-A",
        "quantity_scaled": 10000,
        "scale_factor": 1000,
        "status": "active",
        "notes": "Quality inspected",
        "parent_lots": [{"parent_lot_id": "LOT-RAW-1", "quantity_consumed_scaled": 2000}],
    }
    req = LotRegistrationRequest.model_validate(valid_lot)
    assert req.batch_number == "BATCH-2026-A"
    assert len(req.parent_lots) == 1

    # Negative quantity rejected
    with pytest.raises(ValidationError):
        LotRegistrationRequest.model_validate({**valid_lot, "quantity_scaled": -500})

    # Zero parent consumption quantity rejected
    with pytest.raises(ValidationError):
        LotRegistrationRequest.model_validate(
            {**valid_lot, "parent_lots": [{"parent_lot_id": "LOT-RAW-1", "quantity_consumed_scaled": 0}]}
        )


def test_sqlite_shop_floor_repository_lifecycle():
    """Verify persistence of lots, dispatches, steps, and genealogy querying."""
    conn = sqlite3.connect(":memory:")
    repo = SqliteShopFloorRepository(conn)

    # 1. Register raw material lot
    raw_lot = LotTraceabilityRecord(
        workspace_id="ws_test",
        lot_id="LOT-RAW-ALUM",
        item_id="ALUMINUM-INGOT",
        batch_number="B-ALUM-99",
        quantity_scaled=50_000,
        status="active",
    )
    repo.register_lot(raw_lot)

    # 2. Register finished lot with parent link
    fg_lot = LotTraceabilityRecord(
        workspace_id="ws_test",
        lot_id="LOT-FG-HOUSING",
        item_id="HOUSING-ALUM-01",
        batch_number="B-HOUSING-01",
        quantity_scaled=10_000,
        status="active",
    )
    repo.register_lot(fg_lot, parent_lots=[("LOT-RAW-ALUM", 20_000)])

    # Retrieve lots
    retrieved_raw = repo.get_lot("ws_test", "LOT-RAW-ALUM")
    assert retrieved_raw is not None
    assert retrieved_raw.item_id == "ALUMINUM-INGOT"

    retrieved_fg = repo.get_lot("ws_test", "LOT-FG-HOUSING")
    assert retrieved_fg is not None
    assert retrieved_fg.quantity_scaled == 10_000

    # 3. Save Dispatch and Steps
    step1 = ShopFloorOperationStep(
        step_id="ST-01",
        work_order_id="WO-500",
        operation_sequence=1,
        work_center_id="WC-CASTING",
        operator_id="OP-12",
        status="completed",
        actual_run_minutes=90,
        quantity_completed_scaled=9_500,
        quantity_scrapped_scaled=500,
    )
    dispatch = WorkOrderDispatch(
        workspace_id="ws_test",
        dispatch_id="DISP-500",
        work_order_id="WO-500",
        item_id="HOUSING-ALUM-01",
        scheduled_quantity_scaled=10_000,
        dispatched_lot_id="LOT-FG-HOUSING",
        dispatched_at="2026-10-19T09:00:00Z",
        steps=(step1,),
    )
    repo.save_dispatch(dispatch)

    retrieved_dispatch = repo.get_dispatch("ws_test", "DISP-500")
    assert retrieved_dispatch is not None
    assert retrieved_dispatch.work_order_id == "WO-500"
    assert len(retrieved_dispatch.steps) == 1
    assert retrieved_dispatch.steps[0].quantity_completed_scaled == 9_500

    # 4. Verify Genealogy edges and tree traversal
    edges = repo.get_genealogy_edges("ws_test")
    item_map = repo.get_lot_item_map("ws_test")
    assert len(edges) == 1
    assert edges[0] == ("LOT-RAW-ALUM", "LOT-FG-HOUSING", 20_000)

    # Backward traversal (from FG to RAW)
    backward_tree = traverse_genealogy("LOT-FG-HOUSING", edges, item_map, direction="backward")
    assert backward_tree.lot_id == "LOT-FG-HOUSING"
    assert len(backward_tree.children) == 1
    assert backward_tree.children[0].lot_id == "LOT-RAW-ALUM"

    # Forward traversal (from RAW to FG)
    forward_tree = traverse_genealogy("LOT-RAW-ALUM", edges, item_map, direction="forward")
    assert forward_tree.lot_id == "LOT-RAW-ALUM"
    assert len(forward_tree.children) == 1
    assert forward_tree.children[0].lot_id == "LOT-FG-HOUSING"
