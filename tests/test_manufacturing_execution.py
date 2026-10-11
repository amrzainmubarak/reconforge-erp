"""Independent rational checks for exact BOM expansion and retained WIP."""
from fractions import Fraction

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.manufacturing_execution import allocate_disposition, expand_requirements, quantity


def rounded_even(value: Fraction) -> int:
    base, remainder = divmod(value.numerator, value.denominator)
    return base + int(remainder * 2 > value.denominator or remainder * 2 == value.denominator and base % 2 == 1)


def test_bom_exact_mixed_base_uom_and_large_values() -> None:
    components = [{"item_id": "B", "quantity_scaled": 3500, "quantity_precision": 3},
                  {"item_id": "A", "quantity_scaled": 2, "quantity_precision": 0}]
    requirements = expand_requirements(components, 10, 20)
    assert [(row["item_id"], row["required_quantity_scaled"], row["required_quantity"]) for row in requirements] == [("A", 4, "4"), ("B", 7000, "7.000")]
    assert expand_requirements([{"item_id": "A", "quantity_scaled": 9_000_000_000_000_000_000, "quantity_precision": 6}], 1, 1)[0]["required_quantity_scaled"] == 9_000_000_000_000_000_000


@pytest.mark.parametrize("components,batch,order", [
    ([{"item_id": "A", "quantity_scaled": 1, "quantity_precision": 0}], 3, 2),
    ([{"item_id": "A", "quantity_scaled": 1, "quantity_precision": 0}] * 2, 1, 1),
    ([], 1, 1),
    ([{"item_id": "A", "quantity_scaled": 9_000_000_000_000_000_000, "quantity_precision": 0}], 1, 2),
])
def test_bom_refuses_fractional_base_unit_duplicate_empty_or_overflow(components: list[dict[str, object]], batch: int, order: int) -> None:
    with pytest.raises(FinancePostingError):
        expand_requirements(components, batch, order)


@pytest.mark.parametrize("bad", [1.0, True, "NaN", "Infinity", "-1", "0.0001"])
def test_quantity_refuses_implicit_rounding_or_nonexact_input(bad: object) -> None:
    with pytest.raises(ValueError):
        quantity(bad, 3)


def test_partial_good_and_abnormal_scrap_conserves_actual_material_wip() -> None:
    first = allocate_disposition(original_quantity=10, original_cost=2901, disposed_quantity=0, released_cost=0, good_quantity=3, scrap_quantity=1)
    stage_value = rounded_even(Fraction(2901 * 4, 10))
    assert first["released_cost_minor"] == stage_value == 1160
    assert first["good_cost_minor"] == rounded_even(Fraction(stage_value * 3, 4)) == 870
    assert first["scrap_cost_minor"] == 290
    last = allocate_disposition(original_quantity=10, original_cost=2901, disposed_quantity=4, released_cost=1160, good_quantity=6, scrap_quantity=0)
    assert last["good_cost_minor"] == 1741 and last["wip_after_minor"] == 0
    assert first["good_cost_minor"] + first["scrap_cost_minor"] + last["good_cost_minor"] == 2901


def test_many_partial_dispositions_equal_independent_fraction_oracle() -> None:
    for cost in (501, 1001, 12_345, 9_000_000_000_000_000_000):
        disposed = released = 0
        for good, scrap in ((2, 1), (1, 2), (3, 1)):
            original = Fraction((cost - released) * (good + scrap), 10 - disposed)
            expected = cost - released if good + scrap == 10 - disposed else rounded_even(original)
            result = allocate_disposition(original_quantity=10, original_cost=cost, disposed_quantity=disposed, released_cost=released, good_quantity=good, scrap_quantity=scrap)
            assert result["released_cost_minor"] == expected
            assert result["good_cost_minor"] == rounded_even(Fraction(expected * good, good + scrap))
            disposed += good + scrap
            released += expected
        assert disposed == 10 and released == cost


@pytest.mark.parametrize("cost,good,scrap,disposed,released", [(1, 1, 0, 0, 0), (10, 0, 0, 0, 0), (10, 11, 0, 0, 0), (10, 1, 0, 10, 10), (1, 1, 1, 0, 0)])
def test_refuses_zero_value_excess_or_exhausted_wip(cost: int, good: int, scrap: int, disposed: int, released: int) -> None:
    with pytest.raises(ValueError):
        allocate_disposition(original_quantity=10, original_cost=cost, disposed_quantity=disposed, released_cost=released, good_quantity=good, scrap_quantity=scrap)
