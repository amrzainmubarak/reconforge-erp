"""Public exact values and explicit owner routes without financial coercion."""
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from reconforge.api.routes.manufacturing_supply_plan import PriceCeiling, project_supply, router


@pytest.mark.parametrize("value", [True, 1200.0, 1200, "01200", "1.2e3", "0", "-1200", None])
def test_source_price_ceiling_requires_canonical_positive_minor_text(value: Any) -> None:
    with pytest.raises(ValidationError):
        PriceCeiling(item_code="ITEM", unit_price_minor=value)


def test_full_native_minor_and_scaled_values_and_original_dates_serialize_exactly() -> None:
    original = {"unit_price_ceilings_minor": {"ITEM": 9_000_000_000_000_000_000},
        "unit_prices_minor": [1200, 100], "quantity_scaled": 9_000_000_000_000_000_000,
        "quantity": Decimal("0.500"), "posting_date": date(2026, 10, 7), "row_version": 28}
    assert project_supply(original) == {"unit_price_ceilings_minor": {"ITEM": "9000000000000000000"},
        "unit_prices_minor": ["1200", "100"], "quantity_scaled": "9000000000000000000",
        "quantity": "0.500", "posting_date": "2026-10-07", "row_version": 28}
    assert original["quantity"] == Decimal("0.500")


def test_actual_router_contract_has_native_owner_actions_and_strict_money_text() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    schema = app.openapi()
    root = "/api/v1/manufacturing-supply-plan/plans/{identifier}"
    for suffix in ("approve", "cancel", "handoff", "requisitions", "requisitions/{requisition_id}/quote",
            "requisitions/{requisition_id}/award", "purchases/{order_id}/receive-commit", "purchases/{order_id}/invoice-post"):
        assert "post" in schema["paths"][root + "/" + suffix]
    ceiling = schema["components"]["schemas"]["PriceCeiling"]
    assert ceiling["properties"]["unit_price_minor"]["type"] == "string" and ceiling["additionalProperties"] is False
    assert schema["components"]["schemas"]["PostInvoiceRequest"]["properties"]["expected_budget_version"]["minimum"] == 1
