"""Pure HTTP contracts and scope/permission wiring, not native posting proof."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from reconforge.api import create_api_app
from reconforge.api.authorization import RouteAuthorizationContract, validate_authorization_surface
from reconforge.api.customer_partial_return_contract import (
    CustomerPartialReturnResponseError,
    project_partial_balance,
    project_partial_plan,
    project_partial_response,
)
from reconforge.api.errors import APIError
from reconforge.api.routes import customer_partial_returns as routes
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor

SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
POLICY = {"currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP",
          "currency_registry_version": "synthetic-v1", "currency_registry_digest": "c" * 64}
HISTORY = {"command_id": "retained-command", "expected_history_version": 0, "period_id": "period",
           "posting_date": "2026-10-15", "reason": "Synthetic exact correction"}
RETURN = {**HISTORY, "source_order_id": "stock-original", "quantity_scaled": "12", "journal_code": "CASH",
          "refund_liability_account_code": "REFUND", "cash_account_code": "CASH"}


def native_plan(phase: int = 1, operation: str = "Return") -> dict[str, Any]:
    merchandise = operation in {"Return", "ReverseReturn"}
    prefix = {"Return": "CR2", "Refund": "CRF2", "ReverseReturn": "CR2R", "ReverseRefund": "CRF2R"}[operation]
    return {**SCOPE, **POLICY, "schema_version": "customer-partial-return-v1", "id": prefix + "-" + "a" * 32,
            "operation": operation, "phase": phase, "status": ("Prepared", "Reviewed", "Posted", "Cancelled")[phase],
            "plan_digest": "d" * 64, "source_id": "CRS2-" + "b" * 32, "source_order_id": "stock-original", "invoice_id": "invoice-original",
            "quantity_precision": 0, "quantity_scaled": 12 if merchandise else 0, "credit_minor": 54000 if merchandise else 0,
            "cogs_restored_minor": 16000 if merchandise else 0, "receivable_released_minor": 54000 if merchandise else 0,
            "refund_entitlement_delta_minor": 0, "amount_minor": 70000 if merchandise else 10000,
            "expected_history_version": 0, "posting_date": "2026-10-15", "period_id": "period", "preparer_actor_id": "maker",
            "reviewer_actor_id": "checker" if phase else None, "poster_actor_id": "poster" if phase == 2 else None,
            "original_id": None if operation == "Return" else ("CRF2-" if operation == "ReverseRefund" else "CR2-") + "a" * 32,
            "entries": [{"entry_id": "entry-" + str(index), "purpose": purpose, "validation_digest": "8" * 64,
                         "posting_effect_id": "effect-" + str(index) if phase == 2 else None}
                        for index, purpose in enumerate(("original-revenue", "original-cost") if merchandise else ("customer-refund",))],
            "audit_event_id": "audit", "outbox_event_id": "outbox"}


def native_balance() -> dict[str, Any]:
    return {**SCOPE, **POLICY, "source_order_id": "stock-original", "source_id": "CRS2-" + "b" * 32,
            "source_fingerprint": "f" * 64, "history_fingerprint": "e" * 64, "history_version": 1,
            "gross_minor": 67500, "collected_minor": 10000, "credited_minor": 54000, "returned_quantity_scaled": 12,
            "remaining_quantity_scaled": 3, "quantity_precision": 0, "refund_entitlement_minor": 0, "refunded_minor": 0,
            "refund_due_minor": 0, "outstanding_minor": 3500, "active_plan_id": None}


@pytest.mark.parametrize("model,payload,key", [(routes.ReturnRequest, RETURN, "quantity_scaled"),
                                              (routes.RefundRequest, {**HISTORY, "amount_minor": "1"}, "amount_minor")])
@pytest.mark.parametrize("bad", [True, False, 1, 1.0, "0", "01", "+1", " 1 ", "1.0", "1e3", "-1", "9000000000000000001"])
def test_http_financial_quantities_require_bounded_canonical_positive_text(model, payload, key, bad) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, key: bad})


@pytest.mark.parametrize("model,payload", [(routes.ReturnRequest, RETURN), (routes.RefundRequest, {**HISTORY, "amount_minor": "1"}),
                                         (routes.ReversalRequest, HISTORY)])
@pytest.mark.parametrize("bad", [True, False, -1, 1.0, "0", 256])
def test_history_version_cannot_be_coerced_or_exceed_append_budget(model, payload, bad) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "expected_history_version": bad})


@pytest.mark.parametrize("model,payload", [(routes.ReturnRequest, RETURN), (routes.RefundRequest, {**HISTORY, "amount_minor": "1"}),
                                         (routes.ReversalRequest, HISTORY),
                                         (routes.PhaseRequest, {"command_id": "c", "reason": "explicit", "expected_plan_digest": "d" * 64})])
@pytest.mark.parametrize("extra", [{"actor_id": "spoof"}, {"legal_entity_id": "foreign"}, {"step_up_active": True},
                                    {"tax_minor": "0"}, {"source_snapshot": {}}, {"posting_effect_id": "spoof"}])
def test_http_commands_do_not_accept_client_authority_source_bodies_or_effects(model, payload, extra) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, **extra})


def test_http_exact_large_values_and_required_history_survive_without_rounding() -> None:
    assert routes.ReturnRequest.model_validate({**RETURN, "quantity_scaled": "9007199254740993", "expected_history_version": 255}).quantity_scaled == "9007199254740993"
    assert routes.RefundRequest.model_validate({**HISTORY, "amount_minor": "9000000000000000000"}).amount_minor == "9000000000000000000"
    for key in ("command_id", "expected_history_version", "quantity_scaled"):
        with pytest.raises(ValidationError):
            routes.ReturnRequest.model_validate({name: value for name, value in RETURN.items() if name != key})


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-13-01", "2026-1-1", "٢٠٢٦-١٠-١٥", "2026-10-15T00:00:00Z"])
def test_http_rejects_invalid_or_noncanonical_business_dates_before_native_execution(bad: str) -> None:
    with pytest.raises(ValidationError):
        routes.ReturnRequest.model_validate({**RETURN, "posting_date": bad})


@pytest.mark.parametrize("operation", ["Return", "Refund", "ReverseReturn", "ReverseRefund"])
def test_closed_public_plans_keep_exact_money_policy_and_all_governed_phases(operation: str) -> None:
    for phase in range(4):
        raw = native_plan(phase, operation)
        value = project_partial_plan(raw, SCOPE)
        assert value["phase"] == phase and type(value["phase"]) is int
        assert value["amount_minor"] == str(raw["amount_minor"])
        assert value["quantity_scaled"] == str(raw["quantity_scaled"])
        assert value["currency_registry_digest"] == POLICY["currency_registry_digest"]
        assert raw["amount_minor"] == (70000 if operation in {"Return", "ReverseReturn"} else 10000)


@pytest.mark.parametrize("patch", [{"phase": True}, {"reviewer_actor_id": "maker"}, {"poster_actor_id": "unposted"},
                                    {"legal_entity_id": "foreign"}, {"source_id": "CRS2-bad"}, {"amount_minor": 70001},
                                    {"credit_minor": 0}, {"cogs_restored_minor": 0}, {"quantity_scaled": True},
                                    {"quantity_precision": 7}, {"currency_precision": True}, {"expected_history_version": 256},
                                    {"currency_registry_digest": "not-a-seal"}, {"amount_minor": "70000"},
                                    {"original_id": "CR2-" + "a" * 32}, {"posting_date": "2026-XX-15"}])
def test_public_projection_refuses_invalid_financial_governance_or_scope(patch: dict[str, Any]) -> None:
    with pytest.raises(CustomerPartialReturnResponseError):
        project_partial_plan({**native_plan(), **patch}, SCOPE)


@pytest.mark.parametrize("private", ["source_snapshot", "request", "reason", "cash_dimensions", "domain_plan", "posting_contract", "tenant_id", "password"])
def test_no_private_source_or_financial_object_can_escape_through_plan_or_balance(private: str) -> None:
    for raw, projector in ((native_plan(), project_partial_plan), (native_balance(), project_partial_balance)):
        with pytest.raises(CustomerPartialReturnResponseError):
            projector({**raw, private: {"private": "never-publish"}}, SCOPE)


def test_nested_entry_privacy_and_independence_are_fail_closed() -> None:
    raw = native_plan(2)
    for key, value in (("snapshot", {"private": "original"}), ("dimensions", {"private": "finance"})):
        bad = deepcopy(raw)
        bad["entries"][0][key] = value
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_plan(bad, SCOPE)
    for patch in ({"poster_actor_id": "checker"}, {"entries": [raw["entries"][0], raw["entries"][0]]}):
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_plan({**raw, **patch}, SCOPE)


def test_public_balances_keep_legitimate_credit_liability_separate_from_real_cash() -> None:
    raw = native_balance()
    assert project_partial_balance(raw, SCOPE)["outstanding_minor"] == "3500"
    final = {**raw, "history_version": 256, "collected_minor": 13500, "credited_minor": 67500,
             "returned_quantity_scaled": 15, "remaining_quantity_scaled": 0, "outstanding_minor": 0,
             "refund_entitlement_minor": 13500, "refunded_minor": 3500, "refund_due_minor": 10000}
    assert project_partial_balance(final, SCOPE)["refund_due_minor"] == "10000"
    for patch in ({"outstanding_minor": 1}, {"refund_due_minor": 1}, {"credited_minor": 67501}, {"history_version": 257},
                  {"source_id": None}, {"active_plan_id": "CR1-" + "a" * 32}):
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_balance({**raw, **patch}, SCOPE)


def test_top_level_and_list_projection_do_not_publish_opaque_extra_data() -> None:
    assert project_partial_response({"plans": [native_plan()]}, SCOPE)["plans"][0]["amount_minor"] == "70000"
    for raw in ({"plan": native_plan(), "raw": "private"}, {"plans": [native_plan(), native_plan()]}, {"plans": [native_plan()] * 201}):
        with pytest.raises(CustomerPartialReturnResponseError):
            project_partial_response(raw, SCOPE)


def test_all_nine_routes_have_exact_current_read_and_phase_permission_contracts(tmp_path) -> None:
    contracts = [contract for contract in create_api_app(tmp_path / "unused.db").state.authorization_contracts
                 if contract.path.startswith("/api/v1/customer-partial-returns/")]
    assert len(contracts) == 9 and sum(contract.method == "GET" for contract in contracts) == 3
    assert all(contract.mode == "all" and set(routes.READ) <= set(contract.permissions) for contract in contracts)
    for contract in contracts:
        if contract.method == "GET":
            assert frozenset(contract.permissions) == routes.READ
        else:
            operation = contract.path.rsplit("/", 1)[-1]
            expected = routes.PERMISSIONS[operation if operation in {"review", "post", "cancel"} else "prepare"]
            assert frozenset(contract.permissions) == expected
        weakened = RouteAuthorizationContract(contract.method, contract.path, "all", ("sales.read",))
        with pytest.raises(ValueError, match="drifted"):
            validate_authorization_surface((weakened,))


def test_execute_uses_only_selected_native_connection_scope_and_verified_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = object()
    actor = PostingActor("actor", "actor", frozenset(), step_up_active=True)
    scope = SimpleNamespace(tenant_id="tenant", **SCOPE)
    observed: list[tuple[object, str]] = []
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    user = LocalUser(id="actor", username="actor", display_name="Synthetic actor")
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda request: True)
    monkeypatch.setattr(routes, "_actor", lambda request, user: actor)
    monkeypatch.setattr(routes, "PostgresCustomerPartialReturnsRepository", lambda conn, tenant: observed.append((conn, tenant)) or object())
    monkeypatch.setattr(routes, "execute_postgres_finance_core_scoped", lambda request, run: run(SimpleNamespace(connection=connection), scope))
    value = routes.execute(request, user, lambda owner, current_actor, current_scope: {"plan": native_plan()})
    assert observed == [(connection, "tenant")] and value["plan"]["amount_minor"] == "70000"
    with pytest.raises(APIError) as unavailable:
        routes.execute(request, user, lambda *args: {"plan": {**native_plan(), "source_snapshot": {"private": "do-not-publish"}}})
    assert unavailable.value.status_code == 503 and unavailable.value.code == "customer_partial_return_response_invalid"
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda request: False)
    with pytest.raises(APIError) as disabled:
        routes.execute(request, user, lambda *args: pytest.fail("Local financial fallback must never run."))
    assert disabled.value.status_code == 503


@pytest.mark.parametrize("code,status", [("sales_actor_denied", 403), ("customer_partial_return_not_found", 404),
                                       ("posting_human_required", 403), ("posting_step_up_required", 403),
                                       ("customer_partial_return_state_conflict", 409)])
def test_native_current_authority_and_history_refusals_keep_safe_http_semantics(monkeypatch, code, status) -> None:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    user = LocalUser(id="actor", username="actor", display_name="Synthetic actor")
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda request: True)
    monkeypatch.setattr(routes, "_actor", lambda request, user: object())
    monkeypatch.setattr(routes, "PostgresCustomerPartialReturnsRepository", lambda *args: object())
    monkeypatch.setattr(routes, "execute_postgres_finance_core_scoped", lambda request, run: run(SimpleNamespace(connection=object()), SimpleNamespace(tenant_id="tenant", **SCOPE)))

    def refuse(*args):
        raise FinancePostingError(code, "Current native contract refused this action.")

    with pytest.raises(APIError) as caught:
        routes.execute(request, user, refuse)
    assert caught.value.status_code == status and caught.value.code == code
