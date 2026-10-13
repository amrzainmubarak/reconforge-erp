"""Exact quantities, complete financial exposure and three-human ownership."""
from dataclasses import replace

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.inventory_transfer import (
    TransferInversePreparation,
    TransferPreparation,
    exact_quantity,
    exposed_minor,
    require_capacity,
    require_transition,
)
from reconforge.platform.common import PlatformError


def preparation() -> TransferPreparation:
    return TransferPreparation("T-1", "ITEM", "1", "A/STOCK", "B/STOCK", "period", "2026-10-14",
        "Move approved original stock", {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"})


def test_native_precision_preserves_fraction_and_rejects_unrepresentable_quantity() -> None:
    assert exact_quantity("2.500", 3) == (2500, "2.500")
    assert exact_quantity("1", 0) == (1, "1")
    with pytest.raises(PlatformError):
        exact_quantity("0.001", 0)
    with pytest.raises(FinancePostingError):
        exact_quantity("1", True)


@pytest.mark.parametrize("changes", [{"quantity": 1.0}, {"quantity": "0"}, {"quantity": "NaN"},
    {"from_location": "A"}, {"to_location": "A/OTHER"}, {"to_location": "A/STOCK"},
    {"scope": {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "unowned": "x"}},
    {"posting_date": "2026-02-30"}])
def test_invalid_request_never_invents_scope_or_quantity(changes: dict[str, object]) -> None:
    with pytest.raises((FinancePostingError, PlatformError)):
        replace(preparation(), **changes).payload()  # type: ignore[arg-type]


def test_original_request_and_child_inverse_are_separate_exact_objects() -> None:
    source = preparation().payload()
    child = TransferInversePreparation("IT1-S-A", "a" * 64, 3, "INV-1", "period", "2026-10-14", "Independent inverse").payload()
    assert source["scope"] == {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    assert child["original_id"] == "IT1-S-A" and child["expected_version"] == 3
    assert "quantity" not in child and "scope" not in child


def test_three_distinct_humans_and_terminal_phases() -> None:
    assert require_transition(0, "review", "maker", None, "reviewer") == 1
    assert require_transition(1, "post", "maker", "reviewer", "poster") == 2
    assert require_transition(1, "cancel", "maker", "reviewer", "reviewer") == 3
    for phase, operation, actor in [(0, "review", "maker"), (1, "post", "maker"), (1, "post", "reviewer"),
        (0, "post", "poster"), (2, "cancel", "poster"), (3, "review", "reviewer")]:
        with pytest.raises(FinancePostingError):
            require_transition(phase, operation, "maker", "reviewer", actor)


def test_exclusive_physical_and_fifo_backing_are_both_required() -> None:
    require_capacity(1, 3, 2, 1)
    for physical, reserved, fifo in [(3, 3, 3), (3, 0, 0), (1, 2, 3)]:
        with pytest.raises(FinancePostingError):
            require_capacity(1, physical, reserved, fifo)


def test_full_original_source_value_authority_exceeds_selected_portion() -> None:
    # A one-unit movement can cite a three-unit original layer worth USD 36.
    # Its current remaining value is 12; the complete cited original still is 36.
    assert exposed_minor({"remaining_value_minor": 1200, "sources": [
        {"exposed_amounts_minor": [3600, 1200, 3600, 3600]}]}) == 3600
    with pytest.raises(FinancePostingError):
        exposed_minor({"remaining_value_minor": 0, "sources": []})
    with pytest.raises(FinancePostingError):
        exposed_minor({"remaining_value_minor": 1200, "sources": [{"exposed_amounts_minor": [36.0]}]})
