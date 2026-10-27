"""Pure exact shortage conservation before native material reservation."""
from fractions import Fraction

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.manufacturing_supply_plan import (
    MRPShortageRequisition,
    generate_mrp_shortage_requisitions,
    plan_requirements,
    procurement_headroom,
    require_complete_handoff,
)


def components() -> list[dict[str, object]]:
    return [{"item_id": "A", "item_code": "A", "uom_id": "KG", "uom_code": "KG", "quantity_precision": 3, "quantity_scaled": 12000},
            {"item_id": "B", "item_code": "B", "uom_id": "KG", "uom_code": "KG", "quantity_precision": 3, "quantity_scaled": 1500}]


def test_real_pre_stock_gross_net_and_exclusive_onhand_are_exact() -> None:
    actual = plan_requirements(components(), batch_output_scaled=10, planned_output_scaled=10,
        available_scaled={"A": 4000, "B": 700}, active_reserved_scaled={"A": 1000, "B": 200}, fifo_free_scaled={"A": 4000, "B": 700})
    for row, native_available, prior_reserved in zip(actual, (4000, 700), (1000, 200), strict=True):
        independent_gross = int(Fraction(row["quantity_scaled"]) * Fraction(10, 10))
        independent_onhand = min(independent_gross, native_available - prior_reserved)
        assert row["gross_quantity_scaled"] == independent_gross
        assert row["onhand_reserved_scaled"] == independent_onhand
        assert row["shortage_quantity_scaled"] == independent_gross - independent_onhand
    assert [row["shortage_quantity"] for row in actual] == ["9.000", "1.000"]
    assert procurement_headroom(actual[0]["shortage_quantity_scaled"], [6000]) == 3000
    assert procurement_headroom(actual[0]["shortage_quantity_scaled"], [6000, 3000]) == 0
    require_complete_handoff(12000, 3000, [6000, 3000])


def test_empty_physical_stock_creates_genuine_positive_shortage_without_fake_reservation() -> None:
    actual = plan_requirements(components(), batch_output_scaled=10, planned_output_scaled=10,
        available_scaled={"A": 0, "B": 0}, active_reserved_scaled={"A": 0, "B": 0}, fifo_free_scaled={"A": 0, "B": 0})
    assert all(row["onhand_reserved_scaled"] == 0 for row in actual)
    assert [row["shortage_quantity_scaled"] for row in actual] == [12000, 1500]


@pytest.mark.parametrize("forged", [True, 1000.0, -1, "1000", 9_000_000_000_000_000_001])
def test_native_observation_is_never_coerced(forged: object) -> None:
    with pytest.raises(FinancePostingError):
        plan_requirements(components(), batch_output_scaled=10, planned_output_scaled=10,
            available_scaled={"A": forged, "B": 0}, active_reserved_scaled={"A": 0, "B": 0}, fifo_free_scaled={"A": 0, "B": 0})  # type: ignore[dict-item]


@pytest.mark.parametrize("available,reserved", [({"A": 0}, {"A": 0, "B": 0}),
    ({"A": 0, "B": 0, "C": 0}, {"A": 0, "B": 0}), ({"A": 500, "B": 0}, {"A": 501, "B": 0})])
def test_complete_native_population_and_existing_reservation_conservation_are_required(available: dict[str, int], reserved: dict[str, int]) -> None:
    with pytest.raises(FinancePostingError):
        plan_requirements(components(), batch_output_scaled=10, planned_output_scaled=10,
            available_scaled=available, active_reserved_scaled=reserved, fifo_free_scaled={"A": 0, "B": 0})


@pytest.mark.parametrize("claims", [[6000, 3001], [6000, True], [0], [6000.0]])
def test_duplicate_or_malformed_procurement_capacity_cannot_cover_original_shortage(claims: list[object]) -> None:
    with pytest.raises(FinancePostingError):
        procurement_headroom(9000, claims)  # type: ignore[arg-type]


@pytest.mark.parametrize("onhand,received", [(3000, [6000]), (3000, [9001]), (13000, []), (3000, [9000.0]), (True, [11999])])
def test_handoff_refuses_missing_excess_or_malformed_actual_receiving(onhand: object, received: list[object]) -> None:
    with pytest.raises(FinancePostingError):
        require_complete_handoff(12000, onhand, received)  # type: ignore[arg-type]


def test_posted_physical_quantity_cannot_claim_unvalued_or_already_allocated_fifo() -> None:
    actual = plan_requirements(components(), batch_output_scaled=10, planned_output_scaled=10,
        available_scaled={"A": 12000, "B": 1500}, active_reserved_scaled={"A": 0, "B": 0}, fifo_free_scaled={"A": 7000, "B": 0})
    assert [row["onhand_reserved_scaled"] for row in actual] == [7000, 0]
    assert [row["shortage_quantity_scaled"] for row in actual] == [5000, 1500]


def test_mrp_shortage_requisition_governance_and_headroom_deduplication() -> None:
    actual = plan_requirements(
        components(),
        batch_output_scaled=10,
        planned_output_scaled=10,
        available_scaled={"A": 4000, "B": 700},
        active_reserved_scaled={"A": 1000, "B": 200},
        fifo_free_scaled={"A": 4000, "B": 700},
    )
    # Shortages: A = 9000, B = 1000

    # First requisition generation
    reqs = generate_mrp_shortage_requisitions(
        plan_id="PLAN-MFG-900",
        requirements=actual,
        required_date="2026-12-01",
        unit_prices_minor={"A": 1500, "B": 450},
    )
    assert len(reqs) == 2
    req_a = next(r for r in reqs if r.item_id == "A")
    assert req_a.shortage_quantity_scaled == 9000
    assert req_a.planned_order_quantity_scaled == 9000
    assert req_a.unit_price_minor == 1500
    assert req_a.status == "approved"

    # Re-running with existing claim for 9000 of A suppresses duplicate generation for A
    claims = {"A": [9000]}
    reqs_partial = generate_mrp_shortage_requisitions(
        plan_id="PLAN-MFG-900",
        requirements=actual,
        existing_claims=claims,
        required_date="2026-12-01",
    )
    assert len(reqs_partial) == 1
    assert reqs_partial[0].item_id == "B"
    assert reqs_partial[0].shortage_quantity_scaled == 1000

    # Requisition with invalid date fails
    with pytest.raises(FinancePostingError, match="Invalid required date"):
        generate_mrp_shortage_requisitions(
            plan_id="PLAN-MFG-900",
            requirements=actual,
            required_date="invalid-date",
        )

    # Direct constructor validation
    with pytest.raises(FinancePostingError, match="nonnegative integer is required"):
        MRPShortageRequisition(
            requisition_id="REQ-01",
            plan_id="P1",
            item_id="A",
            shortage_quantity_scaled=-5,
            planned_order_quantity_scaled=10,
            unit_price_minor=100,
            required_date="2026-12-01",
            idempotency_key="key",
        )
