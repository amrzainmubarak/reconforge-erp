"""Independent purchase appropriation arithmetic and immutable request admission."""
from dataclasses import replace
from decimal import localcontext

import pytest

from reconforge.domain.procurement_commitments import BudgetPurchasePreparation, conservation, normalize
from reconforge.domain.procurement_partial import ProcurementPartialError
from tests.test_procurement_multiline import enterprise_request


def test_native_merchandise_exact_total_under_hostile_decimal_context() -> None:
    request = BudgetPurchasePreparation(budget_id="BGT-1", expected_budget_version=3,
                                        order=enterprise_request("BPC1-PO-1"), reason="Approved appropriation")
    with localcontext() as context:
        context.prec = 1
        retained, total = normalize(request)
    assert total == 10 * 1200 + 250 * 2000 // 100 == 17000
    assert retained == request
    assert conservation(17000, 7400, 9600) == 0


@pytest.mark.parametrize("value", [True, 0, -1, "3", 9_000_000_000_000_000_001])
def test_versions_cannot_coerce_or_overflow(value: object) -> None:
    request = BudgetPurchasePreparation(budget_id="BGT-1", expected_budget_version=value,
                                        order=enterprise_request("BPC1-PO-1"), reason="Appropriation")  # type: ignore[arg-type]
    with pytest.raises(ProcurementPartialError, match="version"):
        normalize(request)


def test_reserved_source_namespace_and_exact_conservation() -> None:
    request = BudgetPurchasePreparation(budget_id="BGT-1", expected_budget_version=3,
                                        order=enterprise_request("ORDINARY"), reason="Appropriation")
    with pytest.raises(ProcurementPartialError, match="BPC1"):
        normalize(request)
    with pytest.raises(ProcurementPartialError, match="BPC1"):
        normalize(replace(request, order=enterprise_request("BPC1-")))
    with pytest.raises(ProcurementPartialError, match="exceeds"):
        conservation(17000, 7400, 9601)
