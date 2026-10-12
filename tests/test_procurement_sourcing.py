"""Exact demand, candidate permutation and malformed-offer admission."""
from dataclasses import replace
from decimal import localcontext
from fractions import Fraction
from itertools import permutations

import pytest

from reconforge.domain.procurement_operations import ProcurementError
from reconforge.domain.procurement_partial import ProcurementPartialError
from reconforge.domain.procurement_sourcing import (
    RequirementReference,
    RequisitionPreparation,
    SupplierQuotationPreparation,
    deterministic_winner,
    normalize_requisition,
    quotation_order,
)
from tests.test_procurement_multiline import enterprise_request


def request() -> RequisitionPreparation:
    return RequisitionPreparation(budget_id="budget", order=enterprise_request("SRC5-1"), reason="Actual scoped demand")


def test_quote_preserves_heterogeneous_demand_with_independent_fraction_cost() -> None:
    normalized, ceiling = normalize_requisition(request())
    with localcontext() as context:
        context.prec = 1
        order, total = quotation_order(normalized.order, SupplierQuotationPreparation(supplier_code="ALT",
            unit_prices_minor=(1100, 1800), valid_until="2026-10-31", reason="Retained exact supplier offer"))
    independent = sum(Fraction(line.quantity) * price for line, price in zip(normalized.order.lines, (1100, 1800), strict=True))
    assert independent.denominator == 1 and total == independent.numerator == 15500 and ceiling == 17000
    assert order.number == "BPC1-SRC5-1" and order.supplier_code == "ALT"
    assert [(line.item_code, line.quantity, line.location_code) for line in order.lines] == [
        ("ITEM", "10", "MAIN/STOCK"), ("WEIGHT", "2.50", "NORTH/STOCK")]


def test_winner_is_independent_of_arrival_order_and_exact_supplier_tie() -> None:
    offers = (("offer-B", "B", 17000), ("offer-A", "A", 17000), ("offer-C", "C", 18000))
    assert {deterministic_winner(tuple(order), 17000) for order in permutations(offers)} == {"offer-A"}


@pytest.mark.parametrize("offers", [(), (("A", "SUP", True),), (("A", "SUP", 17000), ("B", "SUP", 16000)),
                                  (("A", "SUP", 17000), ("A", "ALT", 16000)), (("A", "SUP", 17001),)])
def test_invalid_or_over_ceiling_candidates_refuse(offers: tuple[tuple[str, str, int], ...]) -> None:
    with pytest.raises(ProcurementPartialError):
        deterministic_winner(offers, 17000)


@pytest.mark.parametrize("prices", [(True, 2000), (1200,), (0, 2000), (1200, 1)])
def test_quote_refuses_boolean_missing_zero_or_fractional_minor_product(prices: tuple[int, ...]) -> None:
    with pytest.raises(ProcurementError):
        quotation_order(request().order, SupplierQuotationPreparation(supplier_code="SUP", unit_prices_minor=prices,
            valid_until="2026-10-31", reason="Malformed exact quote"))


def test_expired_and_cross_line_requirement_membership_refuse() -> None:
    with pytest.raises(ProcurementPartialError, match="business date"):
        quotation_order(request().order, SupplierQuotationPreparation(supplier_code="SUP", unit_prices_minor=(1200, 2000),
            valid_until="2026-10-02", reason="Expired"))
    reference = RequirementReference(requirement_id="ME1R-" + "A" * 32, requirement_digest="a" * 64)
    with pytest.raises(ProcurementPartialError, match="distinct"):
        normalize_requisition(replace(request(), requirements=(reference, reference)))
    with pytest.raises(ProcurementPartialError, match="matching"):
        normalize_requisition(replace(request(), requirements=(reference,)))


@pytest.mark.parametrize("number", ["ORDINARY", "SRC5-", "SRC5-" + "A" * 26])
def test_only_owned_bounded_source_number_is_admitted(number: str) -> None:
    with pytest.raises(ProcurementPartialError):
        normalize_requisition(replace(request(), order=replace(request().order, number=number)))
