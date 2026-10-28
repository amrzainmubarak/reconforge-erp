"""Narrow authorization-amount and legacy-rule compatibility regressions."""

from __future__ import annotations

from copy import deepcopy
from decimal import ROUND_DOWN, Decimal, localcontext
from fractions import Fraction
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import reconforge.api.routes.reconciliation as routes
from reconforge.api import create_api_app
from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from tests.test_postgres_reconciliation import _Cursor, _ReconciliationConnection


class _ReplayConnection(_ReconciliationConnection):
    """Add the single-row lookup needed by an identical synthetic retry."""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        normalized = " ".join(sql.split()).lower()
        if "from reconforge.reconciliation_inputs" in normalized and "and side = %s and source_id = %s" in normalized:
            assert params is not None
            self.executed.append((sql, params))
            row = next((item for item in self.inputs if (
                item["tenant_id"], item["run_id"], item["side"], item["source_id"]
            ) == params), None)
            return _Cursor(row)
        return super().execute(sql, params)


def _payload(left: str | None, right: str | None) -> routes.ReconciliationRunSubmissionRequest:
    return routes.ReconciliationRunSubmissionRequest(
        run_id="synthetic-run", name="Synthetic", left_source="a", right_source="b", input_hash="synthetic",
        inputs=[
            routes.CanonicalInputRequest(side="Left", source_id="l", record_hash="l", amount=left, currency_code="USD"),
            routes.CanonicalInputRequest(side="Right", source_id="r", record_hash="r", amount=right, currency_code="USD"),
        ],
    )


def _oracle(value: str) -> Fraction:
    text = value.replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return abs(Fraction(text))


def _submit(payload: routes.ReconciliationRunSubmissionRequest) -> dict[str, object]:
    return routes.submit_run(
        SimpleNamespace(state=SimpleNamespace(request_id="synthetic")),  # type: ignore[arg-type]
        payload,
        SimpleNamespace(id="synthetic-user"),  # type: ignore[arg-type]
        idempotency_key="synthetic-key",
    )


def _configure(monkeypatch: pytest.MonkeyPatch, connection: _ReconciliationConnection) -> None:
    monkeypatch.setattr(routes, "_server_only", lambda _request: None)
    monkeypatch.setattr(
        routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant_a", None, None, None),
    )
    monkeypatch.setattr(
        routes, "execute_postgres_reconciliation",
        lambda _request, operation: operation(PostgresReconciliationRepository(connection), "tenant_a"),
    )


def test_api_uses_exact_gross_before_any_repository_write(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _ReplayConnection()
    _configure(monkeypatch, connection)
    amount_seen: list[Decimal | None] = []

    def bounded(_request: Any, **kwargs: Any) -> None:
        amount = kwargs.get("amount")
        amount_seen.append(amount)
        policy = PolicyEvaluationContext(
            user_id="synthetic", username="synthetic", user_permissions=frozenset({"reconciliation.manage"}),
            amount=amount, maximum_amount=Decimal("1232"),
        )
        if not CentralPolicyEngine().evaluate(policy, required_permission="reconciliation.manage").allowed:
            raise APIError(status_code=403, code="synthetic_denial", message="denied")

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", bounded)
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_DOWN
        with pytest.raises(APIError, match="denied"):
            _submit(_payload("-1234.56", "0"))
    assert amount_seen == [Decimal("1234.56")]
    assert connection.executed == [] and connection.inputs == [] and connection.run is None


def test_same_context_retry_keeps_historical_rule_and_repository_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _ReplayConnection()
    _configure(monkeypatch, connection)
    amounts: list[Decimal | None] = []
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", lambda _request, **kw: amounts.append(kw.get("amount")))
    payload = _payload("-1234.56", "0")
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_DOWN
        first = _submit(payload)
        saved_run = deepcopy(connection.run)
        saved_inputs = deepcopy(connection.inputs)
        second = _submit(payload)
    assert first["input_count"] == second["input_count"] == 2
    assert first["run"]["id"] == second["run"]["id"] == "synthetic-run"
    assert first["run"]["rule_json"] == second["run"]["rule_json"]
    assert connection.run == saved_run and connection.inputs == saved_inputs
    assert connection.run is not None and '"policy_amount":"1230"' in connection.run["rule_json"]
    assert amounts == [Decimal("1234.56"), Decimal("1234.56")]


@pytest.mark.parametrize("precision", [3, 7, 28])
@pytest.mark.parametrize("left,right", [
    ("(1234.56)", "0.01"),
    ("9" * 64, "0." + "0" * 61 + "1"),
    ("(1,234.5678)", "-0.0009"),
])
def test_authorization_amount_matches_independent_rational_oracle(
    monkeypatch: pytest.MonkeyPatch, precision: int, left: str, right: str,
) -> None:
    connection = _ReconciliationConnection()
    _configure(monkeypatch, connection)
    seen: list[Decimal | None] = []

    class BeforeWrite(Exception):
        pass

    def capture(_request: Any, **kwargs: Any) -> None:
        seen.append(kwargs.get("amount"))
        raise BeforeWrite

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", capture)
    with localcontext() as ambient:
        ambient.prec = precision
        ambient.rounding = ROUND_DOWN
        with pytest.raises(BeforeWrite):
            _submit(_payload(left, right))
    assert seen[0] is not None and Fraction(seen[0]) == _oracle(left) + _oracle(right)
    assert not connection.executed


def test_unknown_and_invalid_amounts_are_not_silently_converted_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _ReconciliationConnection()
    _configure(monkeypatch, connection)
    seen: list[Decimal | None] = []

    class BeforeWrite(Exception):
        pass

    def capture(_request: Any, **kwargs: Any) -> None:
        seen.append(kwargs.get("amount"))
        raise BeforeWrite

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", capture)
    with pytest.raises(BeforeWrite):
        _submit(_payload("1", None))
    assert seen == [None] and not connection.executed
    for invalid in ("NaN", "Infinity", "malformed", "1e5000000"):
        with pytest.raises(APIError) as error:
            _submit(_payload(invalid, "0"))
        assert error.value.code == "reconciliation_input_amount_invalid"
    assert not connection.executed


def test_oversized_submission_is_rejected_before_amount_calculation(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _ReconciliationConnection()
    _configure(monkeypatch, connection)
    monkeypatch.setattr(routes, "MAX_SUBMISSION_BYTES", 200)

    def should_not_calculate(_inputs: object) -> None:
        raise AssertionError("oversized submission reached amount calculation")

    monkeypatch.setattr(routes, "_policy_amount", should_not_calculate)
    payload = _payload("1", "0")
    payload.inputs[0].attributes = {"synthetic": "x" * 250}
    with pytest.raises(APIError) as error:
        _submit(payload)
    assert error.value.status_code == 413
    assert error.value.code == "reconciliation_request_too_large"
    assert not connection.executed


def test_maximum_bounded_input_count_and_digits_do_not_round_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _ReconciliationConnection()
    _configure(monkeypatch, connection)
    seen: list[Decimal | None] = []

    class BeforeWrite(Exception):
        pass

    def capture(_request: Any, **kwargs: Any) -> None:
        seen.append(kwargs.get("amount"))
        raise BeforeWrite

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", capture)
    payload = _payload("9" * 64, "0." + "0" * 61 + "1")
    payload.inputs.extend(
        routes.CanonicalInputRequest(side="Left", source_id=f"s-{index}", record_hash="h", amount="9" * 64, currency_code="USD")
        for index in range(4_998)
    )
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_DOWN
        with pytest.raises(BeforeWrite):
            _submit(payload)
    expected = 4_999 * _oracle("9" * 64) + _oracle("0." + "0" * 61 + "1")
    assert len(payload.inputs) == 5_000
    assert seen[0] is not None and Fraction(seen[0]) == expected
    assert not connection.executed


@pytest.mark.parametrize("left_currency,right_currency", [("USD", "EUR"), ("USD", ""), ("", ""), ("ZZZ", "ZZZ")])
def test_bounded_policy_refuses_mixed_or_unknown_currency_without_writes(
    monkeypatch: pytest.MonkeyPatch, left_currency: str, right_currency: str,
) -> None:
    connection = _ReconciliationConnection()
    _configure(monkeypatch, connection)
    payload = _payload("10", "10")
    payload.inputs[0].currency_code = left_currency
    payload.inputs[1].currency_code = right_currency
    observed: list[Decimal | None] = []

    def bounded(_request: Any, **kwargs: Any) -> None:
        observed.append(kwargs.get("amount"))
        policy = PolicyEvaluationContext(
            user_id="synthetic", username="synthetic", user_permissions=frozenset({"reconciliation.manage"}),
            amount=kwargs.get("amount"), maximum_amount=Decimal("100"),
        )
        if not CentralPolicyEngine().evaluate(policy, required_permission="reconciliation.manage").allowed:
            raise APIError(status_code=403, code="synthetic_denial", message="denied")

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", bounded)
    with pytest.raises(APIError, match="denied"):
        _submit(payload)
    assert observed == [None]
    assert not connection.executed


def test_unbounded_policy_accepts_legacy_submission_without_currency_and_keeps_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _ReplayConnection()
    _configure(monkeypatch, connection)
    payload = _payload("10.00", "10.00")
    payload.inputs[0].currency_code = ""
    payload.inputs[1].currency_code = ""
    seen: list[Decimal | None] = []

    def unbounded(_request: Any, **kwargs: Any) -> None:
        amount = kwargs.get("amount")
        seen.append(amount)
        policy = PolicyEvaluationContext(
            user_id="synthetic", username="synthetic", user_permissions=frozenset({"reconciliation.manage"}),
            amount=amount,
        )
        assert CentralPolicyEngine().evaluate(policy, required_permission="reconciliation.manage").allowed

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", unbounded)
    response = _submit(payload)
    assert response["input_count"] == 2 and seen == [None]
    assert connection.run is not None and '"policy_amount":"20.00"' in connection.run["rule_json"]
    assert len(connection.inputs) == 2


def test_http_submission_denies_synthetic_ceiling_and_preserves_legacy_retry(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies

    connection = _ReplayConnection()
    user = LocalUser(id="synthetic-user", username="synthetic", display_name="Synthetic")
    permissions = frozenset({"reconciliation.manage"})
    def authenticate(_request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        return (user, permissions) if token == "synthetic-token" else None
    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)
    monkeypatch.setattr(routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant_a", None, None, None))
    monkeypatch.setattr(
        routes, "execute_postgres_reconciliation",
        lambda _request, operation: operation(PostgresReconciliationRepository(connection), "tenant_a"),
    )
    evaluated: list[Decimal | None] = []
    ceiling = [Decimal("1235")]

    def synthetic_policy(_request: Any, **kwargs: Any) -> None:
        amount = kwargs.get("amount")
        evaluated.append(amount)
        policy = PolicyEvaluationContext(
            user_id=user.id, username=user.username, user_permissions=permissions,
            amount=amount, maximum_amount=ceiling[0],
        )
        if not CentralPolicyEngine().evaluate(policy, required_permission="reconciliation.manage").allowed:
            raise APIError(status_code=403, code="synthetic_denial", message="denied")

    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", synthetic_policy)
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    client = TestClient(create_api_app(
        tmp_path / "unused.db", tenant_db_root=tenant_root,
        postgres_dsn="postgresql://reconciliation.test/postgres", postgres_require_tls=False,
    ))
    headers = {"X-ReconForge-Tenant": "tenant_a", "Authorization": "Bearer synthetic-token", "Idempotency-Key": "synthetic-key"}
    payload = _payload("-1234.56", "0").model_dump()
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_DOWN
        first = client.post("/api/v1/reconciliations/runs", headers=headers, json=payload)
        retry = client.post("/api/v1/reconciliations/runs", headers=headers, json=payload)
        saved = deepcopy(connection.run), deepcopy(connection.inputs)
        prior_statements = len(connection.executed)
        ceiling[0] = Decimal("1232")
        denied = client.post("/api/v1/reconciliations/runs", headers=headers, json=payload)
    assert first.status_code == retry.status_code == 202
    assert first.json()["run"]["rule_json"]["policy_amount"] == "1230"
    assert retry.json()["run"]["rule_json"] == first.json()["run"]["rule_json"]
    assert denied.status_code == 403 and len(connection.executed) == prior_statements
    assert (connection.run, connection.inputs) == saved
    assert evaluated == [Decimal("1234.56")] * 3
