from __future__ import annotations

import pandas as pd

from reconforge.io.readers import coerce_dataset_types
from reconforge.schemas import DatasetName


def test_coerce_dataset_types_preserves_invalid_numeric_original_and_marks_missing() -> None:
    frame = pd.DataFrame(
        {
            "move_id": ["SM-1", "SM-2"],
            "date": ["2026-01-01", "2026-01-02"],
            "source_document": ["DOC-1", "DOC-2"],
            "work_order": ["WO-1", "WO-2"],
            "product_code": ["P-1", "P-2"],
            "product_name": ["Product 1", "Product 2"],
            "category": ["Misc", "Misc"],
            "quantity": ["2", "3"],
            "unit_cost": ["25.00", "N/A"],
            "total_cost": ["50.00", "75.00"],
            "warehouse": ["WH1", "WH1"],
            "movement_type": ["ISSUE", "ISSUE"],
            "customer_code": ["CUST-1", "CUST-2"],
            "equipment_serial": ["EQ-1", "EQ-2"],
            "created_by": ["analyst", "analyst"],
        },
    )
    normalized = coerce_dataset_types(frame, DatasetName.STOCK_MOVES)

    assert normalized.loc[1, "unit_cost"] is None
    assert normalized.loc[1, "_reconforge_raw_unit_cost"] == "N/A"
    assert normalized.loc[0, "unit_cost"] is not None


def test_coerce_dataset_types_normalizes_missing_required_text_without_stringifying_null() -> None:
    frame = pd.DataFrame(
        {
            "move_id": ["SM-1"],
            "date": ["2026-01-01"],
            "source_document": ["DOC-1"],
            "work_order": [None],
            "total_cost": ["50.00"],
        }
    )

    normalized = coerce_dataset_types(frame, DatasetName.STOCK_MOVES)

    assert normalized.loc[0, "work_order"] == ""
