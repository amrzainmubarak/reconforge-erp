"""Tests for API dependencies (idempotency keys & cursor pagination)."""

from __future__ import annotations

import json

import pytest

import reconforge.api.dependencies as dependencies_module
from reconforge.api.dependencies import (
    _server_policy_audit_sink,
    get_cursor_pagination,
    get_idempotency_key,
)
from reconforge.api.errors import APIError
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext


def test_cursor_pagination_defaults() -> None:
    params = get_cursor_pagination()
    assert params.cursor is None
    assert params.limit == 50


def test_cursor_pagination_custom() -> None:
    params = get_cursor_pagination(cursor="eyJsYXN0X2lkIjoxMH0=", limit=100)
    assert params.cursor == "eyJsYXN0X2lkIjoxMH0="
    assert params.limit == 100


def test_cursor_pagination_rejects_blank_cursor() -> None:
    with pytest.raises(APIError) as exc_info:
        get_cursor_pagination(cursor="   ", limit=50)
    assert exc_info.value.code == "invalid_cursor"


def test_idempotency_key_absent() -> None:
    assert get_idempotency_key(None, None) is None


def test_idempotency_key_standard_header() -> None:
    key = get_idempotency_key("repeat-repeat-repeat", None)
    assert key == "repeat-repeat-repeat"


def test_idempotency_key_custom_header_alias() -> None:
    key = get_idempotency_key(None, "x-key-999")
    assert key == "x-key-999"


def test_idempotency_key_rejects_blank() -> None:
    with pytest.raises(APIError) as exc_info:
        get_idempotency_key("   ", None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_idempotency_key"


def test_server_policy_audit_sink_persists_only_closed_redacted_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class Repository:
        def append(self, **kwargs: object) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(dependencies_module, "server_audit_administration_enabled", lambda _request: True)
    monkeypatch.setattr(
        dependencies_module,
        "execute_postgres_policy_audit",
        lambda _request, operation: operation(Repository(), "tenant-a"),
    )
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="sensitive-user",
            username="alice",
            user_permissions={"finance_core.validate"},
            tenant_id="tenant-secret",
            workspace_id="workspace-secret",
        ),
        required_permission="finance_core.validate",
    )
    sink = _server_policy_audit_sink(object(), actor_id="sensitive-user")
    assert sink is not None

    from reconforge.auth.policy import audit_policy_decision

    evidence = audit_policy_decision(
        decision,
        actor_id="sensitive-user",
        required_permissions=frozenset({"finance_core.validate"}),
        surface="POST /api/v1/finance-core/journals/validate",
        request_id="request-secret",
        context=PolicyEvaluationContext(
            user_id="sensitive-user",
            username="alice",
            user_permissions={"finance_core.validate"},
            tenant_id="tenant-secret",
            workspace_id="workspace-secret",
        ),
        audit_sink=sink,
    )

    assert len(captured) == 1
    event = captured[0]
    assert event["actor_user_id"] == "sensitive-user"
    assert event["object_type"] == "authorization.policy_decision"
    assert event["object_id"] == evidence.decision_digest
    assert event["after_hash"] == evidence.decision_digest
    metadata = event["metadata"]
    assert isinstance(metadata, dict)
    serialized = json.dumps(metadata, sort_keys=True)
    assert "tenant-secret" not in serialized
    assert "workspace-secret" not in serialized
    assert "request-secret" not in serialized
    assert metadata["policy_decision_evidence"] == evidence.to_dict()
