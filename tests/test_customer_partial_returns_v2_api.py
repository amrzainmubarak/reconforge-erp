"""Closed v2 transport and protocol isolation; not native posting evidence."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.requests import Request

from reconforge.api import create_api_app
from reconforge.api.authorization import RouteAuthorizationContract, validate_authorization_surface
from reconforge.api.customer_partial_return_contract import (
    ALLOCATION_POLICY,
    CustomerPartialReturnResponseError,
    project_partial_balance,
    project_partial_balance_v2,
    project_partial_plan,
    project_partial_plan_v2,
    project_partial_response_v2,
)
from reconforge.api.errors import APIError
from reconforge.api.routes import customer_partial_returns as routes
from reconforge.api.routes.customer_partial_returns_v2 import _select_protocol
from reconforge.api.routes.customer_partial_returns_v2 import router as v2_router
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import PostingActor
from tests.test_customer_partial_returns_api import RETURN, SCOPE, native_balance, native_plan


def native_v2(credit: int, cost: int, phase: int = 1, operation: str = "Return") -> dict[str, Any]:
    raw = native_plan(phase, operation)
    raw.update(schema_version="customer-partial-return-v2", allocation_policy=ALLOCATION_POLICY)
    if operation in {"Return", "ReverseReturn"}:
        raw.update(credit_minor=credit, cogs_restored_minor=cost, receivable_released_minor=credit,
                   refund_entitlement_delta_minor=0, amount_minor=credit + cost)
        raw["entries"] = [entry for entry, amount in zip(raw["entries"], (credit, cost), strict=True) if amount]
    return raw


@pytest.mark.parametrize("credit,cost", [(0, 0), (0, 334), (1000, 0), (1000, 334)])
@pytest.mark.parametrize("operation", ["Return", "ReverseReturn"])
def test_only_nonzero_merchandise_legs_have_entries_in_every_governed_phase(credit: int, cost: int, operation: str) -> None:
    for phase in range(4):
        raw = native_v2(credit, cost, phase, operation)
        result = project_partial_plan_v2(raw, SCOPE)
        assert result["credit_minor"] == str(credit) and result["cogs_restored_minor"] == str(cost)
        assert result["amount_minor"] == str(credit + cost) and result["quantity_scaled"] == "12"
        assert result["entries"] == raw["entries"] and len(result["entries"]) == (credit > 0) + (cost > 0)
        assert result["allocation_policy"] == ALLOCATION_POLICY
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_plan(raw, SCOPE)


@pytest.mark.parametrize("operation", ["Refund", "ReverseRefund"])
def test_refunds_keep_one_positive_native_effect(operation: str) -> None:
    raw = native_v2(0, 0, 2, operation)
    assert len(project_partial_plan_v2(raw, SCOPE)["entries"]) == 1
    patches: tuple[dict[str, Any], ...] = ({"amount_minor": 0}, {"entries": []}, {"credit_minor": 1}, {"quantity_scaled": 1})
    for patch in patches:
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_plan_v2({**raw, **patch}, SCOPE)


@pytest.mark.parametrize("credit,cost", [(0, 0), (0, 334), (1000, 0)])
def test_zero_legs_cannot_be_counterfeited_as_zero_journals_or_legacy_plans(credit: int, cost: int) -> None:
    raw = native_v2(credit, cost, 2)
    with pytest.raises(CustomerPartialReturnResponseError):
        project_partial_plan_v2({**raw, "entries": native_plan(2)["entries"]}, SCOPE)
    legacy = {key: value for key, value in raw.items() if key != "allocation_policy"}
    legacy["schema_version"] = "customer-partial-return-v1"
    with pytest.raises(CustomerPartialReturnResponseError):
        project_partial_plan(legacy, SCOPE)


def test_zero_effect_post_still_requires_three_people_and_immutable_evidence() -> None:
    raw = native_v2(0, 0, 2)
    for patch in ({"reviewer_actor_id": None}, {"poster_actor_id": None}, {"poster_actor_id": "checker"},
                  {"reviewer_actor_id": "maker"}, {"audit_event_id": ""}, {"outbox_event_id": ""},
                  {"plan_digest": "invalid"}, {"quantity_scaled": 0}, {"amount_minor": 1}):
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_plan_v2({**raw, **patch}, SCOPE)


@pytest.mark.parametrize("bad", [None, True, 1, [], {}, "remaining-original-v2", " remaining-original-v1"])
def test_policy_is_one_exact_server_contract_not_a_caller_pricing_rule(bad: Any) -> None:
    with pytest.raises(CustomerPartialReturnResponseError):
        project_partial_plan_v2({**native_v2(1000, 334), "allocation_policy": bad}, SCOPE)
    for field in ("allocation_policy", "protocol_version", "credit_minor", "cogs_restored_minor"):
        with pytest.raises(ValidationError):
            routes.ReturnRequest.model_validate({**RETURN, field: bad})


def test_v2_read_union_preserves_old_dto_values_and_refuses_unknown_or_private_payloads() -> None:
    old, new = native_plan(), native_v2(1000, 334)
    new["id"] = "CR2-" + "9" * 32
    result = project_partial_response_v2({"plans": [old, new]}, SCOPE)
    assert result["plans"] == [project_partial_plan(old, SCOPE), project_partial_plan_v2(new, SCOPE)]
    old_balance = native_balance()
    assert project_partial_response_v2({"balance": old_balance}, SCOPE) == {"balance": project_partial_balance(old_balance, SCOPE)}
    new_balance = {**old_balance, "schema_version": "customer-partial-return-balance-v2", "allocation_policy": ALLOCATION_POLICY}
    assert project_partial_response_v2({"balance": new_balance}, SCOPE) == {"balance": project_partial_balance_v2(new_balance, SCOPE)}
    with pytest.raises(CustomerPartialReturnResponseError):
        project_partial_balance(new_balance, SCOPE)
    for raw in ({"plan": {**new, "schema_version": "customer-partial-return-v3"}},
                {"plans": [new, new]}, {"balance": {**new_balance, "raw_source": {"private": "body"}}},
                {"plan": {**new, "domain_plan": {"before_value_minor": 334}}}):
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_response_v2(raw, SCOPE)
    assert old == native_plan() and old_balance == native_balance()


def test_v2_has_the_same_nine_closed_authority_contracts_and_a_server_only_mode(tmp_path: Path) -> None:
    app = create_api_app(tmp_path / "unused.db")
    contracts = {(contract.method, contract.path): contract for contract in app.state.authorization_contracts}
    old = [contract for (_method, path), contract in contracts.items() if path.startswith("/api/v1/customer-partial-returns/")]
    new = [contract for (_method, path), contract in contracts.items() if path.startswith("/api/v2/customer-partial-returns/")]
    assert len(old) == len(new) == 9
    for contract in new:
        legacy = contracts[(contract.method, contract.path.replace("/api/v2/", "/api/v1/", 1))]
        assert (contract.method, contract.mode, contract.permissions) == (legacy.method, legacy.mode, legacy.permissions)
        with pytest.raises(ValueError, match="drifted"):
            validate_authorization_surface((RouteAuthorizationContract(contract.method, contract.path, "all", ("sales.read",)),))
    assert len(v2_router.routes) == 9
    for route in v2_router.routes:
        assert isinstance(route, APIRoute)
        assert _select_protocol in [dependency.call for dependency in route.dependant.dependencies]
    assert all(contract.path in app.openapi()["paths"] for contract in new)


def test_router_mode_reaches_native_factory_without_accepting_a_version_header(monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"x-protocol-version", b"2")]})
    user = LocalUser(id="actor", username="actor", display_name="Synthetic actor")
    actor = PostingActor("actor", "actor", frozenset(), step_up_active=True)
    observed: list[dict[str, Any]] = []
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda request: True)
    monkeypatch.setattr(routes, "_actor", lambda request, user: actor)
    def factory(*args: Any, **kwargs: Any) -> object:
        observed.append(kwargs)
        return object()

    monkeypatch.setattr(routes, "PostgresCustomerPartialReturnsRepository", factory)
    monkeypatch.setattr(routes, "execute_postgres_finance_core_scoped", lambda request, run: run(SimpleNamespace(connection=object()), SimpleNamespace(tenant_id="tenant", **SCOPE)))
    routes.execute(request, user, lambda *args: {"plan": native_plan()})
    assert observed == [{}]
    with pytest.raises(APIError) as wrong_protocol:
        routes.execute(request, user, lambda *args: {"plan": native_v2(0, 0)})
    assert wrong_protocol.value.code == "customer_partial_return_response_invalid"
    _select_protocol(request)
    result = routes.execute(request, user, lambda *args: {"plan": native_v2(0, 0)})
    assert observed[-1] == {"protocol_version": 2} and result["plan"]["entries"] == []
    for bad in (True, "2", 3, None):
        request.state.customer_partial_return_protocol_version = bad
        with pytest.raises(APIError) as refused:
            routes.execute(request, user, lambda *args: pytest.fail("Invalid server mode cannot reach the native owner."))
        assert refused.value.code == "customer_partial_return_protocol_invalid"


def test_legacy_projection_is_unchanged_and_cannot_silently_accept_v2_metadata() -> None:
    original = native_plan(2)
    before = deepcopy(original)
    value = project_partial_plan(original, SCOPE)
    assert original == before and set(value) == set(original) and "allocation_policy" not in value
    with pytest.raises(CustomerPartialReturnResponseError):
        project_partial_plan({**original, "allocation_policy": ALLOCATION_POLICY}, SCOPE)
