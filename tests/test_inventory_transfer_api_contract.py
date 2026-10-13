"""Finite owner routes, strict source requests and exact public financial values."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from reconforge.api.routes import inventory_transfer as api


def body() -> dict[str, Any]:
    return {"command_id": "original-create", "number": "T-1", "item_code": "ITEM", "quantity": "1",
        "from_location": "A/STOCK", "to_location": "B/STOCK", "period_id": "period", "posting_date": "2026-10-14", "reason": "Original stock transfer"}


@pytest.mark.parametrize("changes", [{"quantity": 1.0}, {"quantity": 1}, {"quantity": True},
    {"quantity": "1e0"}, {"quantity": "-1"}, {"scope": {"workspace_id": "sibling"}}, {"legal_entity_id": "sibling"},
    {"native_movement_id": "fake-native"}])
def test_request_never_coerces_quantity_or_admits_client_scope_or_native_identity(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        api.TransferRequest(**{**body(), **changes})


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, 4])
def test_phase_version_is_an_exact_supported_native_source_version(value: Any) -> None:
    with pytest.raises(ValidationError):
        api.TransferPhaseRequest(command_id="original", expected_digest="a" * 64, expected_version=value, reason="Original review")


def test_public_projection_preserves_full_minor_values_scaled_units_and_dates() -> None:
    original = {"remaining_value_minor": 9_000_000_000_000_000_000, "quantity_scaled": 2500,
        "exposed_amounts_minor": [3600, 1200], "quantity": Decimal("2.500"), "posting_date": date(2026, 10, 14), "row_version": 3}
    assert api.project_transfer(original) == {"remaining_value_minor": "9000000000000000000", "quantity_scaled": "2500",
        "exposed_amounts_minor": ["3600", "1200"], "quantity": "2.500", "posting_date": "2026-10-14", "row_version": 3}
    assert original["quantity_scaled"] == 2500


def test_all_eight_owned_routes_are_explicit_and_additive() -> None:
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    schema = app.openapi()
    root = "/api/v1/inventory-transfer/transfers"
    expected = {(root, "get"), (root, "post"), (root + "/{identifier}", "get"),
        (root + "/{identifier}/evidence", "get"), *((root + "/{identifier}/" + action, "post") for action in ("review", "post", "cancel", "inverse"))}
    actual = {(path, method) for path, methods in schema["paths"].items() for method in methods}
    assert actual == expected
    assert schema["components"]["schemas"]["TransferRequest"]["additionalProperties"] is False


def test_creation_binds_server_scope_before_repository_receives_request(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = SimpleNamespace(workspace_id="work", organization_id="org", legal_entity_id="entity")
    captured = []

    class Service:
        def create(self, prepared: Any, **kwargs: Any) -> dict[str, Any]:
            captured.append((prepared.payload(), kwargs))
            return {"source": {"id": "owned-source"}}

    monkeypatch.setattr(api, "execute", lambda request, user, action, **kwargs: action(Service(), "current-human", scope))
    result = api.create_transfer(None, api.TransferRequest(**body()), None)  # type: ignore[arg-type]
    assert result == {"source": {"id": "owned-source"}}
    assert captured[0][0]["scope"] == {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    assert captured[0][1] == {"command_id": "original-create", "actor": "current-human"}
