"""Public exact values and explicit owner routes without financial coercion."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from reconforge.api.routes.manufacturing_supply_plan import PostInvoiceRequest, PriceCeiling, project_supply, router


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


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1.0, "1"])
def test_ap_publication_requires_a_current_exact_budget_version(value: Any) -> None:
    with pytest.raises(ValidationError):
        PostInvoiceRequest(command_id="original-ap-publication", expected_version=1, document_id="original-invoice",
                           reason="Current appropriation version required", expected_budget_version=value)


@pytest.mark.parametrize("field,value", [("workspace", "sibling"), ("organization_code", "SIBLING"), ("entity_code", "SIBLING")])
def test_source_requisition_refuses_conflicting_body_scope_before_native_creation(monkeypatch: pytest.MonkeyPatch, field: str, value: str) -> None:
    from reconforge.api.errors import APIError
    from reconforge.api.routes import manufacturing_supply_plan as api

    payload = {"command_id": "original-command", "number": "SRC5-MSP-1234567890ABCDEF", "supplier_code": "SUP", "currency_code": "USD",
        "posting_date": "2026-10-04", "period_id": "period", "journal_code": "STOCK", "ap_account_code": "AP", "cash_account_code": "CASH",
        "organization_code": "ORG", "entity_code": "ENTITY", "workspace": "work", "expected_digest": "a" * 64, "budget_id": "budget",
        "reason": "Preserve actual selected scope", "requirement_ids": ["actual-requirement"],
        "lines": [{"item_code": "ITEM", "quantity": "1", "unit_price_minor": "1200", "location_code": "MAIN/STOCK", "policy_code": "FIFO"}], field: value}
    scope = SimpleNamespace(workspace_id="work", organization_code="ORG", entity_code="ENTITY")
    monkeypatch.setattr(api, "execute", lambda request, user, action, **kwargs: action(object(), object(), scope))
    with pytest.raises(APIError) as raised:
        api.create_requisition(None, "actual-plan", api.PlannedRequisitionRequest(**payload), None)  # type: ignore[arg-type]
    assert raised.value.status_code == 403 and raised.value.code == "manufacturing_supply_scope_alias_denied"
