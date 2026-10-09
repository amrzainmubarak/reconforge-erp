"""Partial quantity reservations conserve exact quantities under hostile precision."""
from dataclasses import replace
from decimal import localcontext

import pytest

from reconforge.domain.procurement_partial import (
    PartialQuantityPreparation,
    ProcurementPartialError,
    normalize_order,
    normalize_part,
    require_third_poster,
    reserve_quantity,
)
from tests.test_postgres_procurement_operations import request


def test_exact_partial_cost_and_capacity_do_not_round_with_worker_context() -> None:
    with localcontext() as context:
        context.prec = 2
        part, amount = normalize_part(PartialQuantityPreparation(quantity="123456789.001", posting_date="2026-10-03", period_id="p", reason="Exact source"), 1000)
        assert amount == 123456789001
        assert part.quantity == "123456789.001"
        assert reserve_quantity("0.001", "123456789.002", ("123456789.001",)) == "0"


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-1", "0", "1.001"])
def test_partial_cost_rejects_invalid_quantity_or_fractional_minor_units(quantity: str) -> None:
    with pytest.raises(ProcurementPartialError.__bases__[0]):
        normalize_part(PartialQuantityPreparation(quantity=quantity, posting_date="2026-10-03", period_id="p", reason="Exact source"), 1)


def test_order_document_namespace_and_capacity_are_bounded() -> None:
    with pytest.raises(ProcurementPartialError, match="too long"):
        normalize_order(replace(request(), number="A" * 41))
    with pytest.raises(ProcurementPartialError, match="capacity"):
        reserve_quantity("2", "10", ("6", "3"))


@pytest.mark.parametrize("actors", [("maker", "checker", "checker"), ("maker", "checker", "maker"),
                                   ("maker", "maker", "poster"), ("maker", None, "poster"), ("", "checker", "poster")])
def test_partial_publication_requires_three_retained_canonical_ids(actors: tuple[str, str | None, str]) -> None:
    with pytest.raises(ProcurementPartialError, match="three distinct") as denied:
        require_third_poster(*actors)
    assert denied.value.code == "procurement_partial_duties_conflict"


def test_partial_publication_accepts_a_distinct_poster_without_alias_comparison() -> None:
    require_third_poster("id-maker", "id-checker", "id-poster")
