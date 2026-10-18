"""Closed permission inventory and immutable exact-money API boundary."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from reconforge.api.errors import APIError
from reconforge.api.routes import intercompany_operations as api


def test_all_eleven_routes_require_native_and_owner_permissions() -> None:
    routes = [route for route in api.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 11
    for route in routes:
        operation = "read" if "GET" in route.methods else "review" if route.path.endswith("/review") else "post" if route.path.endswith("/post") else "prepare"
        native = {"read": "read", "prepare": "manage", "review": "validate", "post": "post"}[operation]
        dependencies = [dependency.call for dependency in route.dependant.dependencies]
        expected = frozenset({"intercompany_operations." + operation, "finance_core." + native})
        assert any(getattr(call, "__reconforge_permissions__", None) == expected
                   and getattr(call, "__reconforge_permission_mode__", None) == "all" for call in dependencies)


@pytest.mark.parametrize("operation,native", [("read", "read"), ("prepare", "manage"), ("review", "validate"), ("post", "post")])
def test_authority_checks_both_permissions_without_widening_entity_context(monkeypatch: pytest.MonkeyPatch, operation: str, native: str) -> None:
    calls: list[dict[str, Any]] = []
    scope = SimpleNamespace(tenant_id="tenant", workspace_id="work", organization_id="org", legal_entity_id=None)
    monkeypatch.setattr(api, "request_execution_scope", lambda request: scope)
    monkeypatch.setattr(api, "enforce_server_scoped_permissions", lambda request, **kwargs: calls.append(kwargs))
    api.authority(SimpleNamespace(), operation)
    assert [call["permissions"] for call in calls] == [frozenset({"intercompany_operations." + operation}), frozenset({"finance_core." + native})]
    assert all(call["organization_id"] == "org" and "legal_entity_id" not in call for call in calls)
    scope.legal_entity_id = "entity"
    with pytest.raises(APIError) as caught:
        api.authority(SimpleNamespace(), operation)
    assert caught.value.status_code == 403
    assert len(calls) == 2


@pytest.mark.parametrize("amount", [10001, 10001.0, True, "01", "1e4", "-1", "0"])
def test_cash_api_refuses_coerced_or_noncanonical_minor_values(amount: Any) -> None:
    with pytest.raises(ValidationError):
        api.SettlementRequest(command_id="same", amount_minor=amount, period_id="period", posting_date="2026-10-04", reason="Exact")


def test_cash_api_preserves_large_exact_string_and_refuses_extra_context() -> None:
    value = api.SettlementRequest(command_id="same", amount_minor="4500000000000000000", period_id="period", posting_date="2026-10-04", reason="Exact")
    assert value.amount_minor == "4500000000000000000"
    with pytest.raises(ValidationError):
        api.SettlementRequest(**value.model_dump(), seller_entity_id="other")
