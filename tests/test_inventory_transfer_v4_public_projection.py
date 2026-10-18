"""Actual existing Inventory API projection keeps v4 native integers exact."""

from typing import Any

import pytest

from reconforge.api.routes.inventory_transfer import project_transfer


@pytest.mark.parametrize("cost", [0, 334, 9000000000000000000])
def test_real_projection_preserves_v4_original_integer_meaning_and_safe_wire_text(cost: int) -> None:
    native: dict[str, Any] = {"schema_version": "inventory-transfer-cost-v4", "sources": [{"monetary_return_corrections": [{
        "history_sequence": 7, "allocation_policy": "remaining-dual-currency-v1",
        "plan": {"id": "CR3-" + "a" * 32, "source_id": "MSO-" + "b" * 32,
                 "operation": "Return", "phase": 2, "plan_digest": "c" * 64, "functional_cost_minor": cost},
        "restoration": {"before_quantity_scaled": 3, "before_value_minor": cost, "quantity_scaled": 1,
                        "value_minor": cost, "position": 1, "direction": 1, "consumption_count_at_restore": 2},
    }], "exposed_amounts_minor": [cost, 0]}]}
    projected = project_transfer(native)
    correction = projected["sources"][0]["monetary_return_corrections"][0]
    assert type(native["sources"][0]["monetary_return_corrections"][0]["plan"]["functional_cost_minor"]) is int
    assert correction["plan"]["functional_cost_minor"] == str(cost)
    assert correction["restoration"]["before_value_minor"] == str(cost)
    assert correction["restoration"]["before_quantity_scaled"] == "3"
    assert projected["sources"][0]["exposed_amounts_minor"] == [str(cost), "0"]
    assert type(correction["history_sequence"]) is type(correction["restoration"]["position"]) is int
    assert correction["plan"]["phase"] == 2
